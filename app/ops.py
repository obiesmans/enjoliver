"""
Help the application to be more exploitable
"""

import ctypes
import json
import logging
import os
import shutil

import math
import psutil
import requests
import time
from flask import jsonify
from sqlalchemy.orm import Session

import objs3
import smartdb
from model import Healthz

logger = logging.getLogger(__name__)


def backup_sqlite(cache, application):
    """
    Backup the db by copying it and uploading to a S3 bucket
    During the copy of the db a key is set inside the werkzeug cache to avoid writes
        This key have a TTL and is always unset whatever the status of the backup
    The application config contains the needed keys for the operation:
        - BACKUP_BUCKET_NAME
        - BACKUP_BUCKET_DIRECTORY
        - DB_PATH
        - BACKUP_LOCK_KEY
    :return: Summary of the operation ; copy and upload keys summarize the result success
    """
    start = time.time()
    now_rounded = int(math.ceil(start))
    logger.info("start %s" % now_rounded)
    dest_s3 = "%s/%s.db" % (application.config["BACKUP_BUCKET_DIRECTORY"], now_rounded)
    db_path = application.config["DB_PATH"]
    bucket_name = application.config["BACKUP_BUCKET_NAME"]
    resp = {
        "copy": False,
        "upload": False,
        "source_fs": db_path,
        "dest_fs": "%s-%s.bak" % (db_path, now_rounded),
        "dest_s3": dest_s3 if bucket_name else None,
        "bucket_name": bucket_name,
        "bucket_uri": "s3://%s/%s" % (bucket_name, dest_s3) if application.config[
            "BACKUP_BUCKET_NAME"] else None,
        "size": None,
        "ts": now_rounded,
        "backup_duration": None,
        "lock_duration": None,
        "already_locked": False,
    }
    if cache.get(application.config["BACKUP_LOCK_KEY"]):
        resp["already_locked"] = True
        logger.warning("already_locked")
        return jsonify(resp)

    try:
        source_st = os.stat(resp["source_fs"])
        timeout = math.ceil(source_st.st_size / (1024 * 1024.))
        logger.info("Backup lock key set with timeout == %ss" % timeout)
        cache.set(application.config["BACKUP_LOCK_KEY"], resp["dest_fs"], timeout=timeout)
        os.system('sync')
        shutil.copy2(db_path, resp["dest_fs"])
        dest_st = os.stat(resp["dest_fs"])
        resp["size"], resp["copy"] = dest_st.st_size, True
        logger.info("backup copy done %s size:%s" % (resp["dest_fs"], dest_st.st_size))
    except Exception as e:
        logger.error("<%s %s>" % (e, type(e)))
    finally:
        cache.delete(application.config["BACKUP_LOCK_KEY"])
        resp["lock_duration"] = time.time() - start
        logger.debug("lock duration: %ss" % resp["lock_duration"])

    try:
        if resp["copy"] is False:
            logger.error("copy is False: %s" % resp["dest_fs"])
            raise IOError(resp["dest_fs"])

        s3op = objs3.S3Operator(resp["bucket_name"])
        s3op.upload(resp["dest_fs"], resp["dest_s3"])
        resp["upload"] = True
    except Exception as e:
        logger.error("<%s %s>" % (e, type(e)))

    resp["backup_duration"] = time.time() - start
    logger.info("backup duration: %ss" % resp["backup_duration"])
    return jsonify(resp)


def healthz(application, smart: smartdb.SmartDatabaseClient, request):
    """
    Query all services and return the status
    :return: json
    """
    status = {
        "global": True,
        "flask": True,
        "db": False,
        "matchbox": {k: False for k in application.config["MATCHBOX_URLS"]},
        "discovery": {
            "ipxe": False,
            "ignition": False,
        }

    }
    if application.config["MATCHBOX_URI"] is None:
        application.logger.error("MATCHBOX_URI is None")
    for k in status["matchbox"]:
        try:
            req = requests.get("%s%s" % (application.config["MATCHBOX_URI"], k))
            req.close()
            status["matchbox"][k] = True
        except Exception as e:
            status["matchbox"][k] = False
            status["global"] = False
            logger.error(e)

    # Try a functional testing in discovery stages
    try:
        # here try if a default profile let any new machine boot in iPXE
        req = requests.get("%s%s" % (application.config["MATCHBOX_URI"], "/ipxe"))
        req.close()
        if req.status_code != 200:
            raise AssertionError("/ipxe returned a bad status code: %d" % req.status_code)
        status["discovery"]["ipxe"] = True
    except Exception as e:
        logger.error(e)
        status["global"] = False

    try:
        # create a random mac address to see if matchbox respond us something like it should
        ignition_url = "/ignition?mac=00-00-00-00-00-00"
        req = requests.get("%s%s" % (application.config["MATCHBOX_URI"], ignition_url))
        req.close()
        # Later parse the result to improve the coverage of this check
        _ = json.loads(req.content.decode())

        if req.status_code != 200:
            raise AssertionError("%s returned a bad status code: %d" % (ignition_url, req.status_code))
        status["discovery"]["ignition"] = True
    except Exception as e:
        logger.error(e)
        status["global"] = False

    @smartdb.cockroach_transaction
    def op(caller="/healthz"):
        with smart.new_session() as session:
            return health_check(session, ts=time.time(), who=request.remote_addr)

    try:
        status["db"] = op("/healthz")
        if len(smart.engines) > 1:
            status["dbs"] = smart.engine_urls
    except Exception as e:
        status["global"] = False
        logger.error(e)

    application.logger.debug("%s" % status)
    return status


def shutdown(ec):
    """
    Try to gracefully shutdown the application
    :param ec:
    :return:
    """
    logger.warning("shutdown asked")
    pid_files = [ec.plan_pid_file, ec.matchbox_pid_file]
    gunicorn_pid = None
    pid_list = []

    for pid_file in pid_files:
        try:
            with open(pid_file) as f:
                pid_number = int(f.read())
            os.remove(pid_file)
            pid_list.append(psutil.Process(pid_number))
        except IOError:
            logger.error("IOError -> %s" % pid_file)
        except psutil.NoSuchProcess as e:
            logger.error("%s NoSuchProcess: %s" % (e, pid_file))

    try:
        with open(ec.gunicorn_pid_file) as f:
            pid_number = int(f.read())
        os.remove(ec.gunicorn_pid_file)
        gunicorn_pid = psutil.Process(pid_number)
    except IOError:
        logger.error("IOError -> %s" % ec.gunicorn_pid_file)
    except psutil.NoSuchProcess as e:
        logger.error("%s already dead: %s" % (e, ec.gunicorn_pid_file))

    for pid in pid_list:
        logger.info("SIGTERM -> %s" % pid)
        pid.terminate()
        logger.info("wait -> %s" % pid)
        pid.wait()
        logger.info("%s running: %s " % (pid, pid.is_running()))

    pid_list.append(gunicorn_pid)
    resp = jsonify(["%s" % k for k in pid_list])
    gunicorn_pid.terminate()
    return resp


def health_check(session: Session, ts: int, who: str):
    """
    :param session: a constructed session
    :param ts: timestamp
    :param who: the host who asked for the check
    :return:
    """
    health = session.query(Healthz).first()
    if not health:
        health = Healthz()
        session.add(health)
    health.ts = ts
    health.host = who
    session.commit()
    return True


def health_check_purge(session):
    session.query(Healthz).delete()
    session.commit()
