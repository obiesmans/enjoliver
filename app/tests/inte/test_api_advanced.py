import httplib
import json
import os
import subprocess
import sys
import time
import unittest
import urllib2
from multiprocessing import Process

from sqlalchemy.orm import sessionmaker

import model
from app import api
from app import generator
from common import posts


class TestAPIAdvanced(unittest.TestCase):
    p_bootcfg = Process
    p_api = Process

    func_path = "%s" % os.path.dirname(__file__)
    dbs_path = "%s/dbs" % func_path
    tests_path = "%s" % os.path.split(func_path)[0]
    app_path = os.path.split(tests_path)[0]
    project_path = os.path.split(app_path)[0]
    bootcfg_path = "%s/bootcfg" % project_path
    assets_path = "%s/bootcfg/assets" % project_path

    test_bootcfg_path = "%s/test_bootcfg" % tests_path

    bootcfg_port = int(os.getenv("BOOTCFG_PORT", "8080"))

    bootcfg_address = "0.0.0.0:%d" % bootcfg_port
    bootcfg_endpoint = "http://localhost:%d" % bootcfg_port

    api_port = int(os.getenv("API_PORT", "5000"))

    api_address = "0.0.0.0:%d" % api_port
    api_endpoint = "http://localhost:%d" % api_port

    @staticmethod
    def process_target_bootcfg():
        cmd = [
            "%s/bootcfg_dir/bootcfg" % TestAPIAdvanced.tests_path,
            "-data-path", "%s" % TestAPIAdvanced.test_bootcfg_path,
            "-assets-path", "%s" % TestAPIAdvanced.assets_path,
            "-address", "%s" % TestAPIAdvanced.bootcfg_address,
            "-log-level", "debug"
        ]
        os.write(1, "PID  -> %s\n"
                    "exec -> %s\n" % (
                     os.getpid(), " ".join(cmd)))
        sys.stdout.flush()
        os.execv(cmd[0], cmd)

    @staticmethod
    def process_target_api():
        api.cache.clear()
        api.app.run(host="localhost", port=TestAPIAdvanced.api_port)

    @classmethod
    def setUpClass(cls):
        db_path = "%s/%s.sqlite" % (cls.dbs_path, TestAPIAdvanced.__name__.lower())
        db = "sqlite:///%s" % db_path
        try:
            os.remove(db_path)
        except OSError:
            pass
        engine = api.create_engine(db)
        model.Base.metadata.create_all(engine)
        api.engine = engine

        subprocess.check_output(["make"], cwd=cls.project_path)
        if os.path.isfile("%s/bootcfg_dir/bootcfg" % TestAPIAdvanced.tests_path) is False:
            subprocess.check_output(["make"], cwd=cls.tests_path)
        cls.p_bootcfg = Process(target=TestAPIAdvanced.process_target_bootcfg)
        cls.p_api = Process(target=TestAPIAdvanced.process_target_api)
        os.write(1, "PPID -> %s\n" % os.getpid())
        cls.p_bootcfg.start()
        assert cls.p_bootcfg.is_alive() is True
        cls.p_api.start()
        assert cls.p_api.is_alive() is True

        cls.bootcfg_running(cls.bootcfg_endpoint, cls.p_bootcfg)
        cls.api_running(cls.api_endpoint, cls.p_api)

    @classmethod
    def tearDownClass(cls):
        os.write(1, "TERM -> %d\n" % cls.p_bootcfg.pid)
        sys.stdout.flush()
        cls.p_bootcfg.terminate()
        cls.p_bootcfg.join(timeout=5)
        cls.p_api.terminate()
        cls.p_api.join(timeout=5)

    @staticmethod
    def bootcfg_running(bootcfg_endpoint, p_bootcfg):
        response_body = ""
        response_code = 404
        for i in xrange(100):
            assert p_bootcfg.is_alive() is True
            try:
                request = urllib2.urlopen(bootcfg_endpoint)
                response_body = request.read()
                response_code = request.code
                request.close()
                break

            except httplib.BadStatusLine:
                time.sleep(0.5)

            except urllib2.URLError:
                time.sleep(0.5)

        assert "bootcfg\n" == response_body
        assert 200 == response_code

    @staticmethod
    def api_running(api_endpoint, p_api):
        response_code = 404
        for i in xrange(100):
            assert p_api.is_alive() is True
            try:
                request = urllib2.urlopen(api_endpoint)
                response_code = request.code
                request.close()
                break

            except httplib.BadStatusLine:
                time.sleep(0.5)

            except urllib2.URLError:
                time.sleep(0.5)

        assert 200 == response_code

    @staticmethod
    def clean_sandbox():
        dirs = ["%s/%s" % (
            TestAPIAdvanced.test_bootcfg_path, k) for k in (
                    "profiles", "groups")]
        for d in dirs:
            for f in os.listdir(d):
                if ".json" in f:
                    os.remove("%s/%s" % (d, f))

    def setUp(self):
        self.assertTrue(self.p_bootcfg.is_alive())
        self.assertTrue(self.p_api.is_alive())
        self.clean_sandbox()

    def test_00_healthz(self):
        expect = {
            u'flask': True,
            u'global': True,
            u'bootcfg': {
                u'/': True,
                u'/boot.ipxe': True,
                u'/boot.ipxe.0': True,
                u'/assets': True
            }}
        request = urllib2.urlopen("%s/healthz" % self.api_endpoint)
        response_body = request.read()
        response_code = request.code
        request.close()
        self.assertEqual(json.loads(response_body), expect)
        self.assertEqual(200, response_code)

    def test_01_boot_ipxe(self):
        expect = \
            "#!ipxe\n" \
            "echo start /boot.ipxe\n" \
            ":retry_dhcp\n" \
            "dhcp || goto retry_dhcp\n" \
            "chain http://localhost:5000/ipxe?uuid=${uuid}&mac=${net0/mac:hexhyp}&domain=${domain}&hostname=${hostname}&serial=${serial}\n"
        request = urllib2.urlopen("%s/boot.ipxe" % self.api_endpoint)
        response_body = request.read()
        response_code = request.code
        request.close()
        self.assertEqual(response_code, 200)
        self.assertEqual(response_body, expect)

    def test_01_boot_ipxe_zero(self):
        expect = \
            "#!ipxe\n" \
            "echo start /boot.ipxe\n" \
            ":retry_dhcp\n" \
            "dhcp || goto retry_dhcp\n" \
            "chain http://localhost:5000/ipxe?uuid=${uuid}&mac=${net0/mac:hexhyp}&domain=${domain}&hostname=${hostname}&serial=${serial}\n"
        request = urllib2.urlopen("%s/boot.ipxe" % self.api_endpoint)
        response_body = request.read()
        response_code = request.code
        request.close()
        self.assertEqual(response_code, 200)
        self.assertEqual(response_body, expect)

    def test_02_root(self):
        expect = [
            u'/discovery',
            u'/discovery/interfaces',
            u'/discovery/ignition-journal/<string:uuid>',
            u'/boot.ipxe',
            u'/boot.ipxe.0',
            u'/healthz',
            u'/',
            u'/ipxe']
        request = urllib2.urlopen("%s/" % self.api_endpoint)
        response_body = request.read()
        response_code = request.code
        request.close()
        content = json.loads(response_body)
        self.assertEqual(response_code, 200)
        self.assertItemsEqual(content, expect)

    def test_03_ipxe_404(self):
        with self.assertRaises(urllib2.HTTPError):
            urllib2.urlopen("%s/404" % self.api_endpoint)

    def test_04_ipxe(self):
        marker = "%s-%s" % (TestAPIAdvanced.__name__.lower(), self.test_04_ipxe.__name__)
        ignition_file = "inte-%s.yaml" % marker
        gen = generator.Generator(
            profile_id="id-%s" % marker,
            name="name-%s" % marker,
            ignition_id=ignition_file,
            bootcfg_path=self.test_bootcfg_path)
        gen.dumps()
        request = urllib2.urlopen("%s/ipxe" % self.api_endpoint)
        response_body = request.read()
        response_code = request.code
        request.close()
        expect = "#!ipxe\n" \
                 "echo start /ipxe\n" \
                 "kernel " \
                 "%s/assets/coreos/serve/coreos_production_pxe.vmlinuz " \
                 "coreos.autologin " \
                 "coreos.config.url=%s/ignition?uuid=${uuid}&mac=${net0/mac:hexhyp} " \
                 "coreos.first_boot " \
                 "coreos.oem.id=pxe\n" \
                 "initrd %s/assets/coreos/serve/coreos_production_pxe_image.cpio.gz \n" \
                 "boot\n" % (gen.profile.bootcfg_uri, gen.profile.bootcfg_uri, gen.profile.bootcfg_uri)
        self.assertEqual(response_body, expect)
        self.assertEqual(response_code, 200)

    def test_05_ipxe_selector(self):
        mac = "00:00:00:00:00:00"
        marker = "%s-%s" % (TestAPIAdvanced.__name__.lower(), self.test_05_ipxe_selector.__name__)
        ignition_file = "inte-%s.yaml" % marker
        gen = generator.Generator(
            profile_id="id-%s" % marker,
            name="name-%s" % marker,
            ignition_id=ignition_file,
            selector={"mac": mac},
            bootcfg_path=self.test_bootcfg_path)
        gen.dumps()
        with self.assertRaises(urllib2.HTTPError):
            urllib2.urlopen("%s/ipxe" % self.api_endpoint)

        request = urllib2.urlopen("%s/ipxe?mac=%s" % (self.api_endpoint, mac))
        response_body = request.read()
        response_code = request.code
        request.close()
        expect = "#!ipxe\n" \
                 "echo start /ipxe\n" \
                 "kernel %s/assets/coreos/serve/coreos_production_pxe.vmlinuz " \
                 "coreos.autologin " \
                 "coreos.config.url=%s/ignition?uuid=${uuid}&mac=${net0/mac:hexhyp} " \
                 "coreos.first_boot coreos.oem.id=pxe\n" \
                 "initrd %s/assets/coreos/serve/coreos_production_pxe_image.cpio.gz \n" \
                 "boot\n" % (gen.profile.bootcfg_uri, gen.profile.bootcfg_uri, gen.profile.bootcfg_uri)
        self.assertEqual(response_body, expect)
        self.assertEqual(response_code, 200)

    def test_06_discovery_00(self):
        req = urllib2.Request("%s/discovery" % self.api_endpoint, json.dumps(posts.M01),
                              {'Content-Type': 'application/json'})
        f = urllib2.urlopen(req)
        self.assertEqual(200, f.code)
        response = f.read()
        f.close()
        self.assertEqual(json.loads(response), {u'total_elt': 1, u'new': True})
        req = urllib2.Request("%s/discovery/interfaces" % self.api_endpoint)
        f = urllib2.urlopen(req)
        self.assertEqual(200, f.code)
        response = json.loads(f.read())
        expect = [
            {
                "as_boot": True,
                "chassis_name": "rkt-fe037484-d9c1-4f73-be5e-2c6a7b622fb4",
                "cidrv4": "172.20.0.65/21",
                "ipv4": "172.20.0.65",
                "mac": "52:54:00:e8:32:5b",
                "machine": "b7f5f93a-b029-475f-b3a4-479ba198cb8a",
                "name": "eth0",
                "netmask": 21
            }
        ]
        f.close()
        self.assertEqual(expect, response)

        req = urllib2.Request("%s/discovery" % self.api_endpoint)
        f = urllib2.urlopen(req)
        self.assertEqual(200, f.code)
        response = json.loads(f.read())
        expect = [
            {
                u'boot-info': {
                    u'mac': u'52:54:00:e8:32:5b',
                    u'uuid': u'b7f5f93a-b029-475f-b3a4-479ba198cb8a'
                },
                u'interfaces': [
                    {
                        u'name': u'eth0',
                        u'as_boot': True,
                        u'netmask': 21,
                        u'mac': u'52:54:00:e8:32:5b',
                        u'ipv4': u'172.20.0.65',
                        u'cidrv4': u'172.20.0.65/21'
                    }
                ]
            }
        ]
        f.close()
        self.assertEqual(expect, response)
        req = urllib2.Request("%s/discovery/ignition-journal/b7f5f93a-b029-475f-b3a4-479ba198cb8a" % self.api_endpoint)
        f = urllib2.urlopen(req)
        self.assertEqual(200, f.code)
        response = json.loads(f.read())
        self.assertEqual(39, len(response))

    def test_06_discovery_01(self):
        # TODO
        # print "===> ",
        # ret = subprocess.check_output(
        #     ["%s/assets/discoveryC/serve/discoveryC" % self.bootcfg_path],
        #     env={"DISCOVERY_ADDRESS": "%s/discovery" % self.api_endpoint})
        # print "===> ", ret
        req = urllib2.Request("%s/discovery" % self.api_endpoint, json.dumps(posts.M02),
                              {'Content-Type': 'application/json'})
        f = urllib2.urlopen(req)
        self.assertEqual(200, f.code)
        response = f.read()
        f.close()
        self.assertEqual(json.loads(response), {u'total_elt': 2, u'new': True})

    def test_06_discovery_02(self):
        # TODO
        # subprocess.check_output(
        #     ["%s/assets/discoveryC/serve/discoveryC" % self.bootcfg_path],
        #     env={"DISCOVERY_ADDRESS": "%s/discovery" % self.api_endpoint})
        req = urllib2.Request("%s/discovery" % self.api_endpoint, json.dumps(posts.M03),
                              {'Content-Type': 'application/json'})
        f = urllib2.urlopen(req)
        self.assertEqual(200, f.code)
        response = f.read()
        f.close()
        self.assertEqual(json.loads(response), {u'total_elt': 3, u'new': True})
