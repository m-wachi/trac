# -*- coding: utf-8 -*-
#
# Copyright (C) 2015 Edgewall Software
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.org/wiki/TracLicense.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/log/.

from __future__ import absolute_import

import csv
import io
import six
from six import string_types as basestring


class UnicodeCsvReader(object):

    def __init__(self, iterable, dialect='excel', encoding='utf-8',
                 **fmtparams):
        self.iterable = iterable
        self.dialect = dialect
        self.encoding = encoding
        self.fmtparams = fmtparams
        self.f = None
        self.reader = None

    def __enter__(self):
        if isinstance(self.iterable, basestring):
            if six.PY2:
                f = open(self.iterable, 'rb')
            else:
                f = open(self.iterable, 'r', encoding=self.encoding, newline='')
            self.f = f
        else:
            f = self.iterable
        self.reader = csv.reader(f, dialect=self.dialect, **self.fmtparams)
        return self

    def __exit__(self, type, value, traceback):
        if self.f:
            self.f.close()
            self.f = None

    def __iter__(self):
        return self

    def __next__(self):
        row = next(self.reader)
        if six.PY2:
            row = [value.decode(self.encoding, 'replace') for value in row]
        return row

    next = __next__


class UnicodeCsvWriter(object):

    def __init__(self, fileobj, dialect='excel', encoding='utf-8',
                 **fmtparams):
        self.fileobj = fileobj
        self.dialect = dialect
        self.encoding = encoding
        self.fmtparams = fmtparams
        self.f = None
        self.writer = None

    def __enter__(self):
        if isinstance(self.fileobj, basestring):
            if six.PY2:
                f = open(self.fileobj, 'wb')
            else:
                f = open(self.fileobj, 'w', encoding=self.encoding, newline='')
            self.f = f
        elif six.PY3 and isinstance(self.fileobj, io.BytesIO):
            f = io.TextIOWrapper(self.fileobj, newline='',
                                 encoding=self.encoding, errors='replace',
                                 line_buffering=True)
        else:
            f = self.fileobj
        self.writer = csv.writer(f, dialect=self.dialect, **self.fmtparams)
        return self

    def __exit__(self, type, value, traceback):
        if self.f:
            self.f.close()
            self.f = None
        else:
            self.fileobj.flush()

    def writerow(self, row):
        if not isinstance(row, (list, tuple)):
            row = list(row)
        if six.PY2:
            row = [value.encode(self.encoding, 'replace') for value in row]
        self.writer.writerow(row)

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)
