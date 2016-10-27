import httplib
import json
import os
import subprocess
import urllib2
from multiprocessing import Process

import sys

import time

from app import api
import unittest

from app import generator


class TestAPI(unittest.TestCase):
    p_bootcfg = Process

    func_path = "%s" % os.path.dirname(__file__)
    tests_path = "%s" % os.path.split(func_path)[0]
    app_path = os.path.split(tests_path)[0]
    project_path = os.path.split(app_path)[0]
    bootcfg_path = "%s/bootcfg" % project_path
    assets_path = "%s/bootcfg/assets" % project_path

    test_bootcfg_path = "%s/test_bootcfg" % tests_path

    bootcfg_port = int(os.getenv("BOOTCFG_PORT", "8080"))

    bootcfg_address = "0.0.0.0:%d" % bootcfg_port
    bootcfg_endpoint = "http://localhost:%d" % bootcfg_port

    @staticmethod
    def process_target():
        cmd = [
            "%s/bootcfg_dir/bootcfg" % TestAPI.tests_path,
            "-data-path", "%s" % TestAPI.test_bootcfg_path,
            "-assets-path", "%s" % TestAPI.assets_path,
            "-address", "%s" % TestAPI.bootcfg_address,
            "-log-level", "debug"
        ]
        os.write(1, "PID  -> %s\n"
                    "exec -> %s\n" % (
                     os.getpid(), " ".join(cmd)))
        sys.stdout.flush()
        os.execv(cmd[0], cmd)

    @classmethod
    def setUpClass(cls):
        cls.app = api.app.test_client()
        cls.app.testing = True

        subprocess.check_output(["make"], cwd=cls.project_path)
        if os.path.isfile("%s/bootcfg_dir/bootcfg" % TestAPI.tests_path) is False:
            subprocess.check_output(["make"], cwd=cls.tests_path)
        cls.p_bootcfg = Process(target=TestAPI.process_target)
        os.write(1, "PPID -> %s\n" % os.getpid())
        cls.p_bootcfg.start()
        assert cls.p_bootcfg.is_alive() is True

        cls.bootcfg_running(cls.bootcfg_endpoint, cls.p_bootcfg)

    @classmethod
    def tearDownClass(cls):
        os.write(1, "TERM -> %d\n" % cls.p_bootcfg.pid)
        sys.stdout.flush()
        cls.p_bootcfg.terminate()
        cls.p_bootcfg.join(timeout=5)

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
    def clean_sandbox():
        dirs = ["%s/%s" % (
            TestAPI.test_bootcfg_path, k) for k in (
                    "profiles", "groups")]
        for d in dirs:
            for f in os.listdir(d):
                if ".json" in f:
                    os.remove("%s/%s" % (d, f))

    def setUp(self):
        self.assertTrue(self.p_bootcfg.is_alive())
        self.clean_sandbox()

    def test_00_healthz(self):
        expect = {
            u'flask': True,
            u'global': True,
            u'bootcfg': {
                u'/': True,
                u'/boot.ipxe': True,
                u'/assets': True
            }}
        result = self.app.get('/healthz')
        self.assertEqual(result.status_code, 200)
        content = json.loads(result.data)
        self.assertEqual(expect, content)

    def test_01_boot_ipxe(self):
        expect = \
            "#!ipxe\n" \
            ":retry_dhcp\n" \
            "dhcp || goto retry_dhcp\n" \
            "chain ipxe?uuid=${uuid}&mac=${net0/mac:hexhyp}&domain=${domain}&hostname=${hostname}&serial=${serial}\n"
        result = self.app.get('/boot.ipxe')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data, expect)

    def test_02_root(self):
        expect = [u'/discovery', u'/boot.ipxe', u'/healthz', u'/', u'/ipxe']
        result = self.app.get('/')
        content = json.loads(result.data)
        self.assertEqual(result.status_code, 200)
        self.assertItemsEqual(content, expect)

    def test_03_ipxe_404(self):
        result = self.app.get('/ipxe')
        self.assertEqual(result.data, "404")
        self.assertEqual(result.status_code, 404)

    def test_04_ipxe(self):
        marker = "%s-%s" % (TestAPI.__name__.lower(), self.test_04_ipxe.__name__)
        ignition_file = "inte-%s.yaml" % marker
        gen = generator.Generator(
            profile_id="id-%s" % marker,
            name="name-%s" % marker,
            ignition_id=ignition_file,
            bootcfg_path=self.test_bootcfg_path)
        gen.dumps()
        result = self.app.get('/ipxe')
        expect = "#!ipxe\n" \
                 ":retry_dhcp\n" \
                 "dhcp || goto retry_dhcp\n" \
                 "kernel /assets/coreos/serve/coreos_production_pxe.vmlinuz coreos.autologin coreos.config.url=http://192.168.192.234:8080/ignition?uuid=${uuid}&mac=${net0/mac:hexhyp} coreos.first_boot\n" \
                 "initrd /assets/coreos/serve/coreos_production_pxe_image.cpio.gz \n" \
                 "boot\n"
        self.assertEqual(result.data, expect)
        self.assertEqual(result.status_code, 200)

    def test_05_ipxe_selector(self):
        mac = "00:00:00:00:00:00"
        marker = "%s-%s" % (TestAPI.__name__.lower(), self.test_05_ipxe_selector.__name__)
        ignition_file = "inte-%s.yaml" % marker
        gen = generator.Generator(
            profile_id="id-%s" % marker,
            name="name-%s" % marker,
            ignition_id=ignition_file,
            selector={"mac": mac},
            bootcfg_path=self.test_bootcfg_path)
        gen.dumps()
        result = self.app.get('/ipxe')
        self.assertEqual(result.data, "404")
        self.assertEqual(result.status_code, 404)

        result = self.app.get('/ipxe?mac=%s' % mac)
        expect = "#!ipxe\n" \
                 ":retry_dhcp\n" \
                 "dhcp || goto retry_dhcp\n" \
                 "kernel /assets/coreos/serve/coreos_production_pxe.vmlinuz coreos.autologin coreos.config.url=http://192.168.192.234:8080/ignition?uuid=${uuid}&mac=${net0/mac:hexhyp} coreos.first_boot\n" \
                 "initrd /assets/coreos/serve/coreos_production_pxe_image.cpio.gz \n" \
                 "boot\n"
        self.assertEqual(result.data, expect)
        self.assertEqual(result.status_code, 200)
