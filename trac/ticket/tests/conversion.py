# -*- coding: utf-8 -*-
#
# Copyright (C) 2005-2013 Edgewall Software
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.org/wiki/TracLicense.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/log/.

import os
import unittest

from trac.mimeview.api import Mimeview
from trac.perm import PermissionCache
from trac.test import EnvironmentStub, Mock, MockPerm
from trac.ticket.model import Ticket
from trac.ticket.web_ui import TicketModule
from trac.web.href import Href


class TicketConversionTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub()
        self.env.config.set('trac', 'templates_dir',
                            os.path.join(os.path.dirname(self.env.path),
                                         'templates'))
        self.ticket_module = TicketModule(self.env)
        self.mimeview = Mimeview(self.env)
        self.req = Mock(base_path='/trac.cgi', path_info='',
                        href=Href('/trac.cgi'), chrome={'logo': {}},
                        abs_href=Href('http://example.org/trac.cgi'),
                        environ={}, perm=PermissionCache(self.env, '-'),
                        authname='-', args={}, tz=None,
                        locale='', session=None, form_token=None)

    def tearDown(self):
        self.env.reset_db()

    def _create_a_ticket(self):
        # 1. Creating ticket
        ticket = Ticket(self.env)
        ticket['owner'] = ''
        ticket['reporter'] = 'santa'
        ticket['summary'] = 'Foo'
        ticket['description'] = 'Bar'
        ticket['foo'] = 'This is a custom field'
        ticket.insert()
        return ticket

    def _create_a_ticket_with_email(self):
        ticket = Ticket(self.env)
        ticket['owner'] = 'joe@example.org'
        ticket['reporter'] = 'santa@example.org'
        ticket['cc'] = 'cc1, cc2@example.org'
        ticket['summary'] = 'Foo'
        ticket['description'] = 'Bar'
        ticket.insert()
        return ticket

    def test_conversions(self):
        conversions = self.mimeview.get_supported_conversions(
            'trac.ticket.Ticket')
        self.assertIn(('csv', 'Comma-delimited Text', 'csv',
                       'trac.ticket.Ticket', 'text/csv', 8,
                       self.ticket_module), conversions)
        self.assertIn(('tab', 'Tab-delimited Text', 'tsv',
                       'trac.ticket.Ticket', 'text/tab-separated-values', 8,
                       self.ticket_module), conversions)
        self.assertIn(('rss', 'RSS Feed', 'xml', 'trac.ticket.Ticket',
                       'application/rss+xml', 8, self.ticket_module),
                      conversions)

    def test_csv_conversion(self):
        ticket = self._create_a_ticket()
        csv = self.mimeview.convert_content(self.req, 'trac.ticket.Ticket',
                                            ticket, 'csv')
        self.assertEqual((b'\xef\xbb\xbf'
                          b'id,summary,reporter,owner,description,status,'
                          b'keywords,cc\r\n1,Foo,santa,,Bar,,,\r\n',
                          'text/csv;charset=utf-8', 'csv'), csv)

    def test_csv_conversion_with_obfuscation(self):
        ticket = self._create_a_ticket_with_email()
        csv = self.mimeview.convert_content(self.req, 'trac.ticket.Ticket',
                                            ticket, 'csv')
        self.assertEqual(
            (b'\xef\xbb\xbf'
             b'id,summary,reporter,owner,description,status,keywords,cc\r\n'
             b'1,Foo,santa@\xe2\x80\xa6,joe@\xe2\x80\xa6,Bar,,,'
             b'cc1 cc2@\xe2\x80\xa6\r\n',
             'text/csv;charset=utf-8', 'csv'),
            csv)
        self.req.perm = MockPerm()
        csv = self.mimeview.convert_content(self.req, 'trac.ticket.Ticket',
                                            ticket, 'csv')
        self.assertEqual(
            (b'\xef\xbb\xbf'
             b'id,summary,reporter,owner,description,status,keywords,cc\r\n'
             b'1,Foo,santa@example.org,joe@example.org,Bar,,,'
             b'cc1 cc2@example.org\r\n',
             'text/csv;charset=utf-8', 'csv'),
            csv)

    def test_tab_conversion(self):
        ticket = self._create_a_ticket()
        csv = self.mimeview.convert_content(self.req, 'trac.ticket.Ticket',
                                            ticket, 'tab')
        self.assertEqual((b'\xef\xbb\xbf'
                          b'id\tsummary\treporter\towner\tdescription\t'
                          b'status\tkeywords\tcc\r\n1\tFoo\tsanta\t\tBar\t\t\t'
                          b'\r\n',
                          'text/tab-separated-values;charset=utf-8', 'tsv'),
                         csv)

    def test_tab_conversion_with_obfuscation(self):
        ticket = self._create_a_ticket_with_email()
        csv = self.mimeview.convert_content(self.req, 'trac.ticket.Ticket',
                                            ticket, 'tab')
        self.assertEqual(
            (b'\xef\xbb\xbf'
             b'id\tsummary\treporter\towner\tdescription\tstatus\tkeywords\t'
             b'cc\r\n'
             b'1\tFoo\tsanta@\xe2\x80\xa6\tjoe@\xe2\x80\xa6\tBar\t\t\t'
             b'cc1 cc2@\xe2\x80\xa6\r\n',
             'text/tab-separated-values;charset=utf-8', 'tsv'),
            csv)
        self.req.perm = MockPerm()
        csv = self.mimeview.convert_content(self.req, 'trac.ticket.Ticket',
                                            ticket, 'tab')
        self.assertEqual(
            (b'\xef\xbb\xbf'
             b'id\tsummary\treporter\towner\tdescription\tstatus\tkeywords\t'
             b'cc\r\n'
             b'1\tFoo\tsanta@example.org\tjoe@example.org\tBar\t\t\t'
             b'cc1 cc2@example.org\r\n',
             'text/tab-separated-values;charset=utf-8', 'tsv'),
            csv)

    def test_rss_conversion(self):
        ticket = self._create_a_ticket()
        content, mimetype, ext = self.mimeview.convert_content(
            self.req, 'trac.ticket.Ticket', ticket, 'rss')
        self.assertEqual((u"""<?xml version="1.0"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
  <channel>
    <title>My Project: Ticket #1: Foo</title>
    <link>http://example.org/trac.cgi/ticket/1</link>
    <description>&lt;p&gt;
Bar
&lt;/p&gt;
</description>
    <language>en-us</language>
    <generator>Trac %s</generator>
 </channel>
</rss>""" % self.env.trac_version,
                          'application/rss+xml', 'xml'),
                         (content.decode('utf-8').replace('\r', ''),
                          mimetype, ext))


def suite():
    return unittest.makeSuite(TicketConversionTestCase)


if __name__ == '__main__':
    unittest.main(defaultTest='suite')
