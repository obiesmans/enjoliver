import json
import os
import shutil
import sys
import time
import unittest
from multiprocessing import Process

import requests

from app import api
from app import configs
from app import generator
from common import posts

ec = configs.EnjoliverConfig(importer=__file__)


class TestAPI(unittest.TestCase):
    p_matchbox = Process

    int_path = "%s" % os.path.dirname(__file__)
    dbs_path = "%s/dbs" % int_path
    tests_path = "%s" % os.path.dirname(int_path)
    app_path = os.path.dirname(tests_path)
    project_path = os.path.dirname(app_path)
    matchbox_path = "%s/matchbox" % project_path
    assets_path = "%s/matchbox/assets" % project_path

    test_matchbox_path = "%s/test_matchbox" % tests_path

    @staticmethod
    def process_target_matchbox():
        os.environ["ENJOLIVER_MATCHBOX_PATH"] = TestAPI.test_matchbox_path
        os.environ["ENJOLIVER_MATCHBOX_ASSETS"] = TestAPI.assets_path
        cmd = [
            "%s" % sys.executable,
            "%s/manage.py" % TestAPI.project_path,
            "matchbox",
        ]
        print("PID  -> %s\n"
              "exec -> %s\n" % (
                  os.getpid(), " ".join(cmd)))
        sys.stdout.flush()
        os.execve(cmd[0], cmd, os.environ)

    @classmethod
    def setUpClass(cls):
        time.sleep(0.1)
        try:
            os.remove(ec.db_path)
        except OSError:
            pass
        smart = api.SmartDatabaseClient(ec.db_uri)
        smart.create_base()
        api.SMART = smart
        api.repositories = api.RepositoriesRegister(smart)
        api.CACHE.clear()

        shutil.rmtree(ec.ignition_journal_dir, ignore_errors=True)

        cls.app = api.app.test_client()
        cls.app.testing = True

        cls.p_matchbox = Process(target=TestAPI.process_target_matchbox)
        print("PPID -> %s\n" % os.getpid())
        cls.p_matchbox.start()
        assert cls.p_matchbox.is_alive() is True

        cls.matchbox_running(ec.matchbox_uri, cls.p_matchbox)

    @classmethod
    def tearDownClass(cls):
        print("TERM -> %d\n" % cls.p_matchbox.pid)
        sys.stdout.flush()
        cls.p_matchbox.terminate()
        cls.p_matchbox.join(timeout=5)
        time.sleep(0.2)

    @staticmethod
    def matchbox_running(matchbox_endpoint, p_matchbox):
        response_body = ""
        response_code = 404
        for i in range(10):
            assert p_matchbox.is_alive() is True
            try:
                request = requests.get(matchbox_endpoint)
                response_body = request.content
                response_code = request.status_code
                request.close()
                break

            except requests.exceptions.ConnectionError:
                pass
            time.sleep(0.2)

        assert b"matchbox\n" == response_body
        assert 200 == response_code

    @staticmethod
    def clean_sandbox():
        dirs = ["%s/%s" % (
            TestAPI.test_matchbox_path, k) for k in (
                    "profiles", "groups")]
        for d in dirs:
            for f in os.listdir(d):
                if ".json" in f:
                    os.remove("%s/%s" % (d, f))

    def setUp(self):
        self.assertTrue(self.p_matchbox.is_alive())
        self.clean_sandbox()
        api.CACHE.clear()

    def test_00_healthz(self):
        expect = {
            u'flask': True,
            u'global': False,
            u'db': True,
            'discovery': {'ignition': False, 'ipxe': False},
            u'matchbox': {
                u'/': True,
                u'/boot.ipxe': True,
                u'/boot.ipxe.0': True,
                u'/assets': True,
                u"/metadata": True
            }}
        result = self.app.get('/healthz')
        content = json.loads(result.data.decode())
        self.assertEqual(expect, content)
        self.assertEqual(result.status_code, 503)

    def test_01_boot_ipxe(self):
        expect = [
            "#!ipxe",
            "echo start /boot.ipxe",
            ":retry_dhcp",
            "dhcp || goto retry_dhcp",
        ]
        result = self.app.get('/boot.ipxe')
        self.assertEqual(200, result.status_code)
        self.assertEqual(expect, result.data.decode().split('\n')[:4])

    def test_01_boot_ipxe_0(self):
        expect = [
            "#!ipxe",
            "echo start /boot.ipxe",
            ":retry_dhcp",
            "dhcp || goto retry_dhcp",
        ]
        result = self.app.get('/boot.ipxe.0')
        self.assertEqual(200, result.status_code)
        self.assertEqual(expect, result.data.decode().split('\n')[:4])

    def test_02_root(self):
        result = self.app.get('/')
        self.assertEqual(result.status_code, 200)

    def test_03_ipxe_404(self):
        self.app.get('/ipxe')

    def test_04_ipxe(self):
        marker = "%s-%s" % (TestAPI.__name__.lower(), self.test_04_ipxe.__name__)
        ignition_file = "inte-%s.yaml" % marker
        gen = generator.Generator(
            api_uri=ec.api_uri,
            profile_id="id-%s" % marker,
            name="name-%s" % marker,
            ignition_id=ignition_file,
            matchbox_path=self.test_matchbox_path)
        gen.dumps()
        result = self.app.get('/ipxe')
        expect = "#!ipxe\n" \
                 "kernel " \
                 "%s/assets/coreos/serve/coreos_production_pxe.vmlinuz " \
                 "console=ttyS0 console=ttyS1 " \
                 "coreos.config.url=%s/ignition?uuid=${uuid}&mac=${net0/mac:hexhyp} " \
                 "coreos.first_boot " \
                 "coreos.oem.id=pxe\n" \
                 "initrd %s/assets/coreos/serve/coreos_production_pxe_image.cpio.gz \n" \
                 "boot\n" % (gen.profile.api_uri, gen.profile.api_uri, gen.profile.api_uri)
        expect = str.encode(expect)
        self.assertEqual(expect, result.data)
        self.assertEqual(200, result.status_code)

    def test_05_ipxe_selector(self):
        mac = "00:00:00:00:00:00"
        marker = "%s-%s" % (TestAPI.__name__.lower(), self.test_05_ipxe_selector.__name__)
        ignition_file = "inte-%s.yaml" % marker
        gen = generator.Generator(
            api_uri=ec.api_uri,
            profile_id="id-%s" % marker,
            name="name-%s" % marker,
            ignition_id=ignition_file,
            selector={"mac": mac},
            matchbox_path=self.test_matchbox_path
        )
        gen.dumps()

        result = self.app.get('/ipxe?mac=%s' % mac)
        expect = "#!ipxe\n" \
                 "kernel %s/assets/coreos/serve/coreos_production_pxe.vmlinuz " \
                 "console=ttyS0 console=ttyS1 coreos.config.url=%s/ignition?uuid=${uuid}&mac=${net0/mac:hexhyp} " \
                 "coreos.first_boot coreos.oem.id=pxe\n" \
                 "initrd %s/assets/coreos/serve/coreos_production_pxe_image.cpio.gz \n" \
                 "boot\n" % (gen.profile.api_uri, gen.profile.api_uri, gen.profile.api_uri)
        expect = str.encode(expect)
        self.assertEqual(expect, result.data)
        self.assertEqual(200, result.status_code)

    def test_06_discovery_400(self):
        result = self.app.post('/discovery', data="ok")
        self.assertEqual(result.status_code, 406)

    def test_06_discovery_00(self):
        result = self.app.post('/discovery', data=json.dumps(posts.M01),
                               content_type='application/json')
        self.assertEqual(json.loads(result.data.decode()), {'new-discovery': True})
        self.assertEqual(result.status_code, 200)

    def test_06_discovery_01(self):
        result = self.app.post('/discovery', data=json.dumps(posts.M02),
                               content_type='application/json')
        self.assertEqual(json.loads(result.data.decode()), {'new-discovery': True})
        self.assertEqual(result.status_code, 200)

        result = self.app.post('/discovery', data=json.dumps(posts.M02),
                               content_type='application/json')
        self.assertEqual(json.loads(result.data.decode()), {'new-discovery': False})
        self.assertEqual(result.status_code, 200)

        result = self.app.get("/discovery")
        result_data = json.loads(result.data.decode())
        self.assertEqual(2, len(result_data))

    def test_07_404_fake(self):
        result = self.app.get('/fake')
        self.assertEqual(result.status_code, 404)
