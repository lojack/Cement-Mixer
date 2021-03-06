import unittest
from cmix import app, views
from urlparse import urlparse
import mox
import urllib2
from contextlib import contextmanager
import json

class MockResponse(object):
    def __init__(self, resp_data, code=200, msg='OK'):
        self.resp_data = resp_data
        self.code = code
        self.msg = msg
        self.headers = {'content-type': 'text/xml; charset=utf-8'}


@contextmanager
def mox_response(response):
    m = mox.Mox()
    m.StubOutWithMock(urllib2, 'urlopen')
    urllib2.urlopen(mox.IgnoreArg()).AndReturn(response)
    m.ReplayAll()
    yield
    m.UnsetStubs()
    m.VerifyAll()


class MixerTestCase(unittest.TestCase):
    config_name = 'localhost'
    config_link = 'http://%s:4567' % config_name
    config_trigger = '%s' % config_link
    config_status = '%s/ping' % config_link

    def setUp(self):
        app.config['TESTING'] = True
        app.config['MONGODB_NAME'] = app.config['MONGODB_NAME'] + '_test'
        self.app = app.test_client()

    def tearDown(self):
        views.connection.drop_database(app.config['MONGODB_NAME'])

    def add_server(self, follow_redirects=False):
        return self.app.post('/server', data=dict(
                                link=self.config_link,
                                name=self.config_name,
                                trigger_url=self.config_trigger,
                                status_url=self.config_status
                            ), follow_redirects=follow_redirects)

    def test_empty_db(self):
        rv = self.app.get('/')
        assert 'No build servers' in rv.data
        self.assertEqual(rv.status_code, 200)

    def test_new_server(self):
        rv = self.app.get('/server')
        self.assertEqual(rv.status_code, 200)
        assert '</form>' in rv.data

    def test_add_server(self):
        req_add = self.add_server(follow_redirects=True)
        self.assertEqual(req_add.status_code, 200)
        req_index = self.app.get('/')
        assert self.config_name in req_index.data
        assert self.config_link in req_index.data
        assert self.config_trigger in req_index.data

    def test_delete_server(self):
        req_add = self.add_server()
        self.assertEqual(req_add.status_code, 302)
        path = urlparse(req_add.location).path

        req_index = self.app.get('/')
        assert self.config_name in req_index.data

        req_delete = self.app.delete(path, follow_redirects=True)
        self.assertEqual(req_delete.status_code, 200)

        req_index2 = self.app.get('/')
        assert self.config_name not in req_index2.data

    def test_update_server(self):
        # add server and get path
        req_add = self.add_server()
        self.assertEqual(req_add.status_code, 302)
        path = urlparse(req_add.location).path

        # verify path exists
        req_change = self.app.get(path)
        self.assertEqual(req_change.status_code, 200)

        req_update = self.app.post(path, data=dict(
                                link=self.config_link,
                                name='%s_test' % self.config_name,
                                trigger_url=self.config_trigger,
                                status_url=self.config_status
                            ), follow_redirects=True)
        self.assertEqual(req_update.status_code, 200)

        req_index = self.app.get('/')
        assert '%s_test' % self.config_name in req_index.data

    def test_failed_build(self):
        req_add = self.add_server()
        self.assertEqual(req_add.status_code, 302)
        path = urlparse(req_add.location).path

        from cmix.runner import update_builds
        with mox_response(MockResponse("OK", 200)):
            update_builds()

        req_json = self.app.get('/json')
        server_data = json.loads(req_json.data)
        assert server_data[0]['build_success'] == True

        with mox_response(MockResponse("Not OK", 400)):
            update_builds()

        req_json = self.app.get('/json')
        server_data = json.loads(req_json.data)
        assert server_data[0]['build_success'] == False

        with mox_response(MockResponse("OK", 200)):
            update_builds()

        req_json = self.app.get('/json')
        server_data = json.loads(req_json.data)
        assert server_data[0]['build_success'] == True

        m = mox.Mox()

        # raise unavailable when calling urlopen()
        m.StubOutWithMock(urllib2, 'urlopen')
        urllib2.urlopen(
                mox.IgnoreArg()).AndRaise(urllib2.URLError("Unavailable")
            )
        m.ReplayAll()

        update_builds()

        req_json = self.app.get('/json')
        server_data = json.loads(req_json.data)
        assert server_data[0]['build_success'] == False

    def test_failed_first(self):
        req_add = self.add_server()
        self.assertEqual(req_add.status_code, 302)
        path = urlparse(req_add.location).path

        from cmix.runner import update_builds
        with mox_response(MockResponse("Not OK", 400)):
            update_builds()

        req_json = self.app.get('/json')
        server_data = json.loads(req_json.data)
        assert server_data[0]['build_success'] == False

    def test_monitoring(self):
        from flask import session
        req_mon = self.app.post('/monitoring', data={'active': 'false'})
        self.assertEqual(req_mon.status_code, 200)
        req_mon = self.app.post('/monitoring', data={'active': 'true'})
        self.assertEqual(req_mon.status_code, 200)

    def test_trigger(self):
        req_add = self.add_server()
        self.assertEqual(req_add.status_code, 302)
        path = urlparse(req_add.location).path

        m = mox.Mox()

        # Stub out a successful response
        with mox_response(MockResponse("Build Started")):
            req_trigger = self.app.post('%s/trigger' % path, data=dict())
            self.assertEqual(req_trigger.status_code, 200)

        # Stub out server unavailable response
        m.StubOutWithMock(urllib2, 'urlopen')
        urllib2.urlopen(
                mox.IgnoreArg()).AndRaise(urllib2.URLError("Unavailable")
            )
        m.ReplayAll()

        req_trigger2 = self.app.post('%s/trigger' % path, data=dict())
        self.assertEqual(req_trigger2.status_code, 503)
        m.UnsetStubs()
        m.VerifyAll()

        # Stub out 400 error
        with mox_response(MockResponse("Error", code=400)):
            req_trigger = self.app.post('%s/trigger' % path, data=dict())
            self.assertEqual(req_trigger.status_code, 503)

    def test_json(self):
        req_json1 = self.app.get('/json')
        self.assertEqual(req_json1.status_code, 200)
        req_add = self.add_server(follow_redirects=True)
        req_json2 = self.app.get('/json')
        self.assertEqual(req_json2.status_code, 200)



if __name__ == '__main__':
    unittest.main()
