# -*- coding: utf-8 -*-
#
# Copyright (C) 2003-2009 Edgewall Software
# Copyright (C) 2003-2006 Jonas Borgström <jonas@edgewall.com>
# Copyright (C) 2006 Matthew Good <trac@matt-good.net>
# Copyright (C) 2005-2006 Christian Boos <cboos@edgewall.org>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.org/wiki/TracLicense.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/log/.
#
# Author: Jonas Borgström <jonas@edgewall.com>
#         Matthew Good <trac@matt-good.net>

import math
import re
import sys
import time
from datetime import tzinfo, timedelta, datetime, date
from locale import getlocale, LC_TIME

try:
    import babel
    from babel import Locale
    from babel.core import LOCALE_ALIASES
    from babel.dates import (
        format_datetime as babel_format_datetime, 
        format_date as babel_format_date,
        format_time as babel_format_time,
        get_datetime_format, get_date_format,
        get_time_format, get_month_names,
        get_period_names, get_day_names
    )
except ImportError:
    babel = None

from trac.core import TracError
from trac.util.text import to_unicode, getpreferredencoding
from trac.util.translation import _, ngettext, get_available_locales

# Date/time utilities

# -- conversion

def to_datetime(t, tzinfo=None):
    """Convert `t` into a `datetime` object, using the following rules:
    
     - If `t` is already a `datetime` object and `tzinfo` is None, it is simply
       returned.
     - If `t` is already a `datetime` object and `tzinfo` is not None, it will
       adjust `t` to `tzinfo` timezone.
     - If `t` is None, the current time will be used.
     - If `t` is a number, it is interpreted as a timestamp.
     
    If no `tzinfo` is given, the local timezone will be used.

    Any other input will trigger a `TypeError`.
    """
    if t is None:
        return datetime.now(tzinfo or localtz)
    elif isinstance(t, datetime):
        if tzinfo is not None:
            if t.tzinfo is None:
                t = t.replace(tzinfo=tzinfo)
            else:
                t = tzinfo.normalize(t.astimezone(tzinfo))
        return t
    elif isinstance(t, date):
        tz = tzinfo or localtz
        t = tz.localize(datetime(t.year, t.month, t.day))
        return tz.normalize(t)
    elif isinstance(t, (int, long, float)):
        if not (_min_ts <= t <= _max_ts):
            # Handle microsecond timestamps for 0.11 compatibility
            t *= 0.000001
        if t < 0 and isinstance(t, float):
            # Work around negative fractional times bug in Python 2.4
            # http://bugs.python.org/issue1646728
            frac, integer = math.modf(t)
            return datetime.fromtimestamp(integer - 1, tzinfo or localtz) \
                   + timedelta(seconds=frac + 1)
        return datetime.fromtimestamp(t, tzinfo or localtz)
    raise TypeError('expecting datetime, int, long, float, or None; got %s' %
                    type(t))

def to_timestamp(dt):
    """Return the corresponding POSIX timestamp"""
    if dt:
        diff = dt - _epoc
        return diff.days * 86400 + diff.seconds
    else:
        return 0

def to_utimestamp(dt):
    """Return a microsecond POSIX timestamp for the given `datetime`."""
    if not dt:
        return 0
    diff = dt - _epoc
    return (diff.days * 86400000000L + diff.seconds * 1000000
            + diff.microseconds)

def from_utimestamp(ts):
    """Return the `datetime` for the given microsecond POSIX timestamp."""
    return _epoc + timedelta(microseconds=ts or 0)

# -- formatting

_units = (
    (3600*24*365, lambda r: ngettext('%(num)d year', '%(num)d years', r)),
    (3600*24*30,  lambda r: ngettext('%(num)d month', '%(num)d months', r)),
    (3600*24*7,   lambda r: ngettext('%(num)d week', '%(num)d weeks', r)),
    (3600*24,     lambda r: ngettext('%(num)d day', '%(num)d days', r)),
    (3600,        lambda r: ngettext('%(num)d hour', '%(num)d hours', r)),
    (60,          lambda r: ngettext('%(num)d minute', '%(num)d minutes', r)))

def pretty_timedelta(time1, time2=None, resolution=None):
    """Calculate time delta between two `datetime` objects.
    (the result is somewhat imprecise, only use for prettyprinting).

    If either `time1` or `time2` is None, the current time will be used
    instead.
    """
    time1 = to_datetime(time1)
    time2 = to_datetime(time2)
    if time1 > time2:
        time2, time1 = time1, time2
    
    diff = time2 - time1
    age_s = int(diff.days * 86400 + diff.seconds)
    if resolution and age_s < resolution:
        return ''
    if age_s <= 60 * 1.9:
        return ngettext('%(num)i second', '%(num)i seconds', age_s)
    for u, format_units in _units:
        r = float(age_s) / float(u)
        if r >= 1.9:
            r = int(round(r))
            return format_units(r)
    return ''


_BABEL_FORMATS = {
    'datetime': {'short': '%x %H:%M', 'medium': '%x %X', 'long': '%x %X',
                 'full': '%x %X'},
    'date': {'short': '%x', 'medium': '%x', 'long': '%x', 'full': '%x'},
    'time': {'short': '%H:%M', 'medium': '%X', 'long': '%X', 'full': '%X'},
}
_ISO8601_FORMATS = {
    'datetime': {
        '%x %X': 'iso8601', '%x': 'iso8601date', '%X': 'iso8601time',
        'short': '%Y-%m-%dT%H:%M', 'medium': '%Y-%m-%dT%H:%M:%S',
        'long': 'iso8601', 'full': 'iso8601',
        'iso8601': 'iso8601', None: 'iso8601'},
    'date': {
        '%x %X': 'iso8601', '%x': 'iso8601date', '%X': 'iso8601time',
        'short': 'iso8601date', 'medium': 'iso8601date',
        'long': 'iso8601date', 'full': 'iso8601date',
        'iso8601': 'iso8601date', None: 'iso8601date'},
    'time': {
        '%x %X': 'iso8601', '%x': 'iso8601date', '%X': 'iso8601time',
        'short': '%H:%M', 'medium': '%H:%M:%S',
        'long': 'iso8601time', 'full': 'iso8601time',
        'iso8601': 'iso8601time', None: 'iso8601time'},
}

def _format_datetime_without_babel(t, format, tzinfo):
    tz = tzinfo or localtz
    t = to_datetime(t, tzinfo).astimezone(tz)
    normalize_Z = False
    if format.lower().startswith('iso8601'):
        if 'date' in format:
            format = '%Y-%m-%d'
        elif 'time' in format:
            format = '%H:%M:%S%z'
            normalize_Z = True
        else:
            format = '%Y-%m-%dT%H:%M:%S%z'
            normalize_Z = True
    text = t.strftime(str(format))
    if normalize_Z:
        text = text.replace('+0000', 'Z')
        if not text.endswith('Z'):
            text = text[:-2] + ":" + text[-2:]
    encoding = getlocale(LC_TIME)[1] or getpreferredencoding() \
               or sys.getdefaultencoding()
    return unicode(text, encoding, 'replace')

def format_datetime(t=None, format='%x %X', tzinfo=None, locale=None):
    """Format the `datetime` object `t` into an `unicode` string

    If `t` is None, the current time will be used.
    
    The formatting will be done using the given `format`, which consist
    of conventional `strftime` keys. In addition the format can be 'iso8601'
    to specify the international date format (compliant with RFC 3339).

    `tzinfo` will default to the local timezone if left to `None`.
    """
    if locale == 'iso8601':
        format = _ISO8601_FORMATS['datetime'].get(format, format)
        return _format_datetime_without_babel(t, format, tzinfo)
    if babel and locale:
        if format == '%x':
            return babel_format_date(t, 'medium', locale)
        if format == '%X':
            t = to_datetime(t, tzinfo)
            return babel_format_time(t, 'medium', None, locale)
        if format in ('%x %X', None):
            format = 'medium'
        if format in _BABEL_FORMATS['datetime']:
            t = to_datetime(t, tzinfo)
            return babel_format_datetime(t, format, None, locale)
    format = _BABEL_FORMATS['datetime'].get(format, format)
    return _format_datetime_without_babel(t, format, tzinfo)

def format_date(t=None, format='%x', tzinfo=None, locale=None):
    """Convenience method for formatting the date part of a `datetime` object.
    See `format_datetime` for more details.
    """
    if locale == 'iso8601':
        format = _ISO8601_FORMATS['date'].get(format, format)
        return _format_datetime_without_babel(t, format, tzinfo)
    if format == 'iso8601':
        format = 'iso8601date'
    if babel and locale:
        if format in ('%x', None):
            format = 'medium'
        if format in _BABEL_FORMATS['date']:
            t = to_datetime(t, tzinfo)
            return babel_format_date(t, format, locale)
    format = _BABEL_FORMATS['date'].get(format, format)
    return _format_datetime_without_babel(t, format, tzinfo)

def format_time(t=None, format='%X', tzinfo=None, locale=None):
    """Convenience method for formatting the time part of a `datetime` object.
    See `format_datetime` for more details.
    """
    if locale == 'iso8601':
        format = _ISO8601_FORMATS['time'].get(format, format)
        return _format_datetime_without_babel(t, format, tzinfo)
    if format == 'iso8601':
        format = 'iso8601time'
    if babel and locale:
        if format in ('%X', None):
            format = 'medium'
        if format in _BABEL_FORMATS['time']:
            t = to_datetime(t, tzinfo)
            return babel_format_time(t, format, None, locale)
    format = _BABEL_FORMATS['time'].get(format, format)
    return _format_datetime_without_babel(t, format, tzinfo)

def get_date_format_hint(locale=None):
    """Present the default format used by `format_date` in a human readable
    form.
    This is a format that will be recognized by `parse_date` when reading a
    date.
    """
    if locale == 'iso8601':
        return 'YYYY-MM-DD'
    if babel and locale:
        format = get_date_format('medium', locale=locale)
        return format.pattern

    t = datetime(1999, 10, 29, tzinfo=utc)
    tmpl = format_date(t, tzinfo=utc)
    return tmpl.replace('1999', 'YYYY', 1).replace('99', 'YY', 1) \
               .replace('10', 'MM', 1).replace('29', 'DD', 1)

def get_datetime_format_hint(locale=None):
    """Present the default format used by `format_datetime` in a human readable
    form.
    This is a format that will be recognized by `parse_date` when reading a
    date.
    """
    if locale == 'iso8601':
        return u'YYYY-MM-DDThh:mm:ss±hh:mm'
    if babel and locale:
        date_pattern = get_date_format('medium', locale=locale).pattern
        time_pattern = get_time_format('medium', locale=locale).pattern
        format = get_datetime_format('medium', locale=locale)
        return format.replace('{0}', time_pattern) \
                     .replace('{1}', date_pattern)

    t = datetime(1999, 10, 29, 23, 59, 58, tzinfo=utc)
    tmpl = format_datetime(t, tzinfo=utc)
    ampm = format_time(t, '%p', tzinfo=utc)
    if ampm:
        tmpl = tmpl.replace(ampm, 'a', 1)
    return tmpl.replace('1999', 'YYYY', 1).replace('99', 'YY', 1) \
               .replace('10', 'MM', 1).replace('29', 'DD', 1) \
               .replace('23', 'hh', 1).replace('11', 'hh', 1) \
               .replace('59', 'mm', 1).replace('58', 'ss', 1)

def get_month_names_jquery_ui(req):
    """Get the month names for the jQuery UI datepicker library"""
    locale = req.lc_time
    if locale == 'iso8601':
        locale = req.locale
    if babel and locale:
        month_names = {}
        for width in ('wide', 'abbreviated'):
            names = get_month_names(width, locale=locale)
            month_names[width] = [names[i + 1] for i in xrange(12)]
        return month_names

    return {
        'wide': (
            'January', 'February', 'March', 'April', 'May', 'June', 'July',
            'August', 'September', 'October', 'November', 'December'),
        'abbreviated': (
            'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep',
            'Oct', 'Nov', 'Dec'),
    }

def get_day_names_jquery_ui(req):
    """Get the day names for the jQuery UI datepicker library"""
    locale = req.lc_time
    if locale == 'iso8601':
        locale = req.locale
    if babel and locale:
        day_names = {}
        for width in ('wide', 'abbreviated', 'narrow'):
            names = get_day_names(width, locale=locale)
            day_names[width] = [names[(i + 6) % 7] for i in xrange(7)]
        return day_names

    return {
        'wide': ('Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday',
                 'Friday', 'Saturday'),
        'abbreviated': ('Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'),
        'narrow': ('Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'),
    }

def get_date_format_jquery_ui(locale):
    """Get the date format for the jQuery UI datepicker library."""
    if locale == 'iso8601':
        return 'yy-mm-dd'
    if babel and locale:
        values = {'yyyy': 'yy', 'y': 'yy', 'M': 'm', 'MM': 'mm', 'MMM': 'M',
                  'd': 'd', 'dd': 'dd'}
        return get_date_format('medium', locale=locale).format % values

    t = datetime(1999, 10, 29, tzinfo=utc)
    tmpl = format_date(t, tzinfo=utc)
    return tmpl.replace('1999', 'yy', 1).replace('99', 'y', 1) \
               .replace('10', 'mm', 1).replace('29', 'dd', 1)

def get_time_format_jquery_ui(locale):
    """Get the time format for the jQuery UI timepicker addon."""
    if locale == 'iso8601':
        return 'hh:mm:ssz'  # XXX timepicker doesn't support 'ISO_8601'
    if babel and locale:
        values = {'h': 'h', 'hh': 'hh', 'H': 'h', 'HH': 'hh',
                  'm': 'm', 'mm': 'mm', 's': 's', 'ss': 'ss',
                  'a': 'TT'}
        return get_time_format('medium', locale=locale).format % values

    t = datetime(1999, 10, 29, 23, 59, 58, tzinfo=utc)
    tmpl = format_time(t, tzinfo=utc)
    ampm = format_time(t, '%p', tzinfo=utc)
    if ampm:
        tmpl = tmpl.replace(ampm, 'TT', 1)
    return tmpl.replace('23', 'hh', 1).replace('11', 'hh', 1) \
               .replace('59', 'mm', 1).replace('58', 'ss', 1)

def get_timezone_list_jquery_ui(t=None):
    """Get timezone list for jQuery timepicker addon"""
    t = datetime.now(utc) if t is None else utc.localize(t)
    zones = set(t.astimezone(get_timezone(tz)).strftime('%z')
                for tz in all_timezones)
    return [{'value': 'Z', 'label': '+00:00'} \
            if zone == '+0000' else zone[:-2] + ':' + zone[-2:]
            for zone in sorted(zones, key=lambda tz: int(tz))]

def get_first_week_day_jquery_ui(req):
    """Get first week day for jQuery date picker"""
    locale = req.lc_time
    if locale == 'iso8601':
        return 1 # Monday
    if babel and locale:
        if not locale.territory and locale.language in LOCALE_ALIASES:
            locale = Locale.parse(LOCALE_ALIASES[locale.language])
        return (locale.first_week_day + 1) % 7
    return 0 # Sunday

def is_24_hours(locale):
    """Returns `True` for 24 hour time formats."""
    if locale == 'iso8601':
        return True
    t = datetime(1999, 10, 29, 23, tzinfo=utc)
    tmpl = format_datetime(t, tzinfo=utc, locale=locale)
    return '23' in tmpl

def http_date(t=None):
    """Format `datetime` object `t` as a rfc822 timestamp"""
    t = to_datetime(t).astimezone(utc)
    weekdays = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
    months = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep',
              'Oct', 'Nov', 'Dec')
    return '%s, %02d %s %04d %02d:%02d:%02d GMT' % (
        weekdays[t.weekday()], t.day, months[t.month - 1], t.year,
        t.hour, t.minute, t.second)


# -- parsing

_ISO_8601_RE = re.compile(r'''
    (\d\d\d\d)(?:-?(\d\d)(?:-?(\d\d))?)?    # date
    (?:
        [T ]
        (\d\d)(?::?(\d\d)(?::?(\d\d)        # time
        (?:[,.](\d{1,6}))?)?)?              # microseconds
    )?
    (Z?(?:([-+])?(\d\d):?(\d\d)?)?)?$       # timezone
    ''', re.VERBOSE)

def _parse_date_iso8601(text, tzinfo):
    match = _ISO_8601_RE.match(text)
    if match:
        try:
            g = match.groups()
            years = g[0]
            months = g[1] or '01'
            days = g[2] or '01'
            hours, minutes, seconds, useconds = [x or '00' for x in g[3:7]]
            useconds = (useconds + '000000')[:6]
            z, tzsign, tzhours, tzminutes = g[7:11]
            if z:
                tz = timedelta(hours=int(tzhours or '0'),
                               minutes=int(tzminutes or '0')).seconds / 60
                if tz == 0:
                    tzinfo = utc
                else:
                    tzinfo = FixedOffset(-tz if tzsign == '-' else tz,
                                         '%s%s:%s' %
                                         (tzsign, tzhours, tzminutes))
            tm = [int(x) for x in (years, months, days,
                                   hours, minutes, seconds, useconds)]
            t = tzinfo.localize(datetime(*tm))
            return tzinfo.normalize(t)
        except ValueError:
            pass

    return None

def parse_date(text, tzinfo=None, locale=None, hint='date'):
    tzinfo = tzinfo or localtz
    text = text.strip()

    dt = _parse_date_iso8601(text, tzinfo)
    if dt is None and locale != 'iso8601':
        if babel and locale:
            dt = _i18n_parse_date(text, tzinfo, locale)
        else:
            for format in ['%x %X', '%x, %X', '%X %x', '%X, %x', '%x', '%c',
                           '%b %d, %Y']:
                try:
                    tm = time.strptime(text, format)
                    dt = tzinfo.localize(datetime(*tm[0:6]))
                    dt = tzinfo.normalize(dt)
                    break
                except ValueError:
                    continue
    if dt is None:
        dt = _parse_relative_time(text, tzinfo)
    if dt is None:
        hint = {'datetime': get_datetime_format_hint,
                'date': get_date_format_hint
               }.get(hint, lambda(l): hint)(locale)
        raise TracError(_('"%(date)s" is an invalid date, or the date format '
                          'is not known. Try "%(hint)s" instead.', 
                          date=text, hint=hint), _('Invalid Date'))
    # Make sure we can convert it to a timestamp and back - fromtimestamp()
    # may raise ValueError if larger than platform C localtime() or gmtime()
    try:
        to_datetime(to_timestamp(dt), tzinfo)
    except ValueError:
        raise TracError(_('The date "%(date)s" is outside valid range. '
                          'Try a date closer to present time.', date=text),
                          _('Invalid Date'))
    return dt

def _i18n_parse_date_patterns():
    if not babel:
        return {}

    format_keys = {
        'y': ('y', 'Y'),
        'M': ('M',),
        'd': ('d',),
        'h': ('h', 'H'),
        'm': ('m',),
        's': ('s',),
    }
    patterns = {}

    for locale in get_available_locales():
        regexp = [r'[0-9]+']

        date_format = get_date_format('medium', locale=locale)
        time_format = get_time_format('medium', locale=locale)
        datetime_format = get_datetime_format('medium', locale=locale)

        formats = (
            datetime_format.replace('{0}', time_format.format) \
                           .replace('{1}', date_format.format),
            date_format.format)

        orders = []
        for format in formats:
            order = []
            for key, chars in format_keys.iteritems():
                for char in chars:
                    idx = format.find('%(' + char)
                    if idx != -1:
                        order.append((idx, key))
                        break
            order.sort()
            order = dict((key, idx) for idx, (_, key) in enumerate(order))
            orders.append(order)

        month_names = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
        }
        if formats[0].find('%(MMM)s') != -1:
            for width in ('wide', 'abbreviated'):
                names = get_month_names(width, locale=locale)
                for num, name in names.iteritems():
                    name = name.lower()
                    month_names[name] = num
        regexp.extend(month_names.iterkeys())

        period_names = {'am': 'am', 'pm': 'pm'}
        if formats[0].find('%(a)s') != -1:
            names = get_period_names(locale=locale)
            for period, name in names.iteritems():
                name = name.lower()
                period_names[name] = period
        regexp.extend(period_names.iterkeys())

        patterns[locale] = {
            'orders': orders,
            'regexp': re.compile('(%s)' % '|'.join(regexp),
                                 re.IGNORECASE | re.UNICODE),
            'month_names': month_names,
            'period_names': period_names,
        }

    return patterns

_I18N_PARSE_DATE_PATTERNS = _i18n_parse_date_patterns()

def _i18n_parse_date(text, tzinfo, locale):
    pattern = _I18N_PARSE_DATE_PATTERNS.get(str(locale))
    if pattern is None:
        return None

    regexp = pattern['regexp']
    period_names = pattern['period_names']
    month_names = pattern['month_names']
    text = text.lower()
    for order in pattern['orders']:
        try:
            return _i18n_parse_date_0(text, order, regexp, period_names,
                                      month_names, tzinfo)
        except ValueError:
            continue

    return None

def _i18n_parse_date_0(text, order, regexp, period_names, month_names, tzinfo):
    matches = regexp.findall(text)
    if not matches:
        return None

    # remove am/pm markers on ahead
    period = None
    for idx, match in enumerate(matches):
        period = period_names.get(match)
        if period is not None:
            del matches[idx]
            break

    # for date+time, use 0 seconds if seconds are missing
    if 's' in order and len(matches) == 5:
        matches.insert(order['s'], 0)

    values = {}
    for key, idx in order.iteritems():
        if idx < len(matches):
            value = matches[idx]
            if key == 'y':
                if len(value) == 2 and value.isdigit():
                    value = '20' + value
            values[key] = value

    if 'y' not in values or 'M' not in values or 'd' not in values:
        raise ValueError

    for key in ('y', 'M', 'd'):
        value = values[key]
        value = month_names.get(value)
        if value is not None:
            if key == 'M':
                values[key] = value
            else:
                values[key], values['M'] = values['M'], value
            break

    values = dict((key, int(value)) for key, value in values.iteritems())
    values.setdefault('h', 0)
    values.setdefault('m', 0)
    values.setdefault('s', 0)

    if period and values['h'] <= 12:
        if period == 'am':
            values['h'] %= 12
        elif period == 'pm':
            values['h'] = values['h'] % 12 + 12

    t = tzinfo.localize(datetime(*(values[k] for k in 'yMdhms')))
    return tzinfo.normalize(t)

_REL_TIME_RE = re.compile(
    r'(\d+\.?\d*)\s*'
    r'(second|minute|hour|day|week|month|year|[hdwmy])s?\s*'
    r'(?:ago)?$')
_time_intervals = dict(
    second=lambda v: timedelta(seconds=v),
    minute=lambda v: timedelta(minutes=v),
    hour=lambda v: timedelta(hours=v),
    day=lambda v: timedelta(days=v),
    week=lambda v: timedelta(weeks=v),
    month=lambda v: timedelta(days=30 * v),
    year=lambda v: timedelta(days=365 * v),
    h=lambda v: timedelta(hours=v),
    d=lambda v: timedelta(days=v),
    w=lambda v: timedelta(weeks=v),
    m=lambda v: timedelta(days=30 * v),
    y=lambda v: timedelta(days=365 * v),
)
_TIME_START_RE = re.compile(r'(this|last)\s*'
                            r'(second|minute|hour|day|week|month|year)$')
_time_starts = dict(
    second=lambda now: now.replace(microsecond=0),
    minute=lambda now: now.replace(microsecond=0, second=0),
    hour=lambda now: now.replace(microsecond=0, second=0, minute=0),
    day=lambda now: now.replace(microsecond=0, second=0, minute=0, hour=0),
    week=lambda now: now.replace(microsecond=0, second=0, minute=0, hour=0) \
                     - timedelta(days=now.weekday()),
    month=lambda now: now.replace(microsecond=0, second=0, minute=0, hour=0,
                                  day=1),
    year=lambda now: now.replace(microsecond=0, second=0, minute=0, hour=0,
                                  day=1, month=1),
)

def _parse_relative_time(text, tzinfo):
    now = tzinfo.localize(datetime.now())
    if text == 'now':
        return now
    if text == 'today':
        return now.replace(microsecond=0, second=0, minute=0, hour=0)
    if text == 'yesterday':
        return now.replace(microsecond=0, second=0, minute=0, hour=0) \
               - timedelta(days=1)
    match = _REL_TIME_RE.match(text)
    if match:
        (value, interval) = match.groups()
        return now - _time_intervals[interval](float(value))
    match = _TIME_START_RE.match(text)
    if match:
        (which, start) = match.groups()
        dt = _time_starts[start](now)
        if which == 'last':
            if start == 'month':
                if dt.month > 1:
                    dt = dt.replace(month=dt.month - 1)
                else:
                    dt = dt.replace(year=dt.year - 1, month=12)
            else:
                dt -= _time_intervals[start](1)
        return dt
    return None

# -- formatting/parsing helper functions

def user_time(req, func, *args, **kwargs):
    """A helper function which passes to `tzinfo` and `locale` keyword
    arguments of `func` using `req` parameter. It is expected to be used with
    `format_*` and `parse_date` methods in `trac.util.datefmt` package.

    :param req: a instance of `Request`
    :param func: a function which must accept `tzinfo` and `locale` keyword
                 arguments
    :param args: arguments which pass to `func` function
    :param kwargs: keyword arguments which pass to `func` function
    """
    if 'tzinfo' not in kwargs:
        kwargs['tzinfo'] = getattr(req, 'tz', None)
    if 'locale' not in kwargs:
        kwargs['locale'] = getattr(req, 'lc_time', None)
    return func(*args, **kwargs)

# -- timezone utilities

class FixedOffset(tzinfo):
    """Fixed offset in minutes east from UTC."""

    def __init__(self, offset, name):
        self._offset = timedelta(minutes=offset)
        self.zone = name

    def __str__(self):
        return self.zone

    def __repr__(self):
        return '<FixedOffset "%s" %s>' % (self.zone, self._offset)

    def utcoffset(self, dt):
        return self._offset

    def tzname(self, dt):
        return self.zone

    def dst(self, dt):
        return _zero

    def localize(self, dt, is_dst=False):
        if dt.tzinfo is not None:
            raise ValueError('Not naive datetime (tzinfo is already set)')
        return dt.replace(tzinfo=self)

    def normalize(self, dt, is_dst=False):
        if dt.tzinfo is None:
            raise ValueError('Naive time (no tzinfo set)')
        return dt


STDOFFSET = timedelta(seconds=-time.timezone)
if time.daylight:
    DSTOFFSET = timedelta(seconds=-time.altzone)
else:
    DSTOFFSET = STDOFFSET

DSTDIFF = DSTOFFSET - STDOFFSET


class LocalTimezone(tzinfo):
    """A 'local' time zone implementation"""
    
    def __str__(self):
        return self.tzname(datetime.now())
    
    def __repr__(self):
        return '<LocalTimezone "%s" %s "%s" %s>' % (
            time.tzname[False], STDOFFSET,
            time.tzname[True], DSTOFFSET)

    def utcoffset(self, dt):
        if self._isdst(dt):
            return DSTOFFSET
        else:
            return STDOFFSET

    def dst(self, dt):
        if self._isdst(dt):
            return DSTDIFF
        else:
            return _zero

    def tzname(self, dt):
        return time.tzname[self._isdst(dt)]

    def _isdst(self, dt):
        tt = (dt.year, dt.month, dt.day,
              dt.hour, dt.minute, dt.second,
              dt.weekday(), 0, -1)
        try:
            stamp = time.mktime(tt)
            tt = time.localtime(stamp)
            return tt.tm_isdst > 0
        except OverflowError:
            return False

    def localize(self, dt, is_dst=False):
        if dt.tzinfo is not None:
            raise ValueError('Not naive datetime (tzinfo is already set)')
        return dt.replace(tzinfo=self)

    def normalize(self, dt, is_dst=False):
        if dt.tzinfo is None:
            raise ValueError('Naive time (no tzinfo set)')
        return dt


utc = FixedOffset(0, 'UTC')
utcmin = datetime.min.replace(tzinfo=utc)
utcmax = datetime.max.replace(tzinfo=utc)
_epoc = datetime(1970, 1, 1, tzinfo=utc)
_zero = timedelta(0)
_min_ts = -(1 << 31)
_max_ts = (1 << 31) - 1

localtz = LocalTimezone()

# Use a makeshift timezone implementation if pytz is not available.
# This implementation only supports fixed offset time zones.
#
_timezones = [
    FixedOffset(0, 'UTC'),
    FixedOffset(-720, 'GMT -12:00'), FixedOffset(-660, 'GMT -11:00'),
    FixedOffset(-600, 'GMT -10:00'), FixedOffset(-540, 'GMT -9:00'),
    FixedOffset(-480, 'GMT -8:00'),  FixedOffset(-420, 'GMT -7:00'),
    FixedOffset(-360, 'GMT -6:00'),  FixedOffset(-300, 'GMT -5:00'),
    FixedOffset(-240, 'GMT -4:00'),  FixedOffset(-180, 'GMT -3:00'),
    FixedOffset(-120, 'GMT -2:00'),  FixedOffset(-60, 'GMT -1:00'),
    FixedOffset(0, 'GMT'),           FixedOffset(60, 'GMT +1:00'),
    FixedOffset(120, 'GMT +2:00'),   FixedOffset(180, 'GMT +3:00'),
    FixedOffset(240, 'GMT +4:00'),   FixedOffset(300, 'GMT +5:00'),
    FixedOffset(360, 'GMT +6:00'),   FixedOffset(420, 'GMT +7:00'),
    FixedOffset(480, 'GMT +8:00'),   FixedOffset(540, 'GMT +9:00'),
    FixedOffset(600, 'GMT +10:00'),  FixedOffset(660, 'GMT +11:00'),
    FixedOffset(720, 'GMT +12:00'),  FixedOffset(780, 'GMT +13:00')]
_tzmap = dict([(z.zone, z) for z in _timezones])

all_timezones = [z.zone for z in _timezones]

try:
    import pytz

    _tzoffsetmap = dict([(tz.utcoffset(None), tz) for tz in _timezones
                         if tz.zone != 'UTC'])

    def timezone(tzname):
        """Fetch timezone instance by name or raise `KeyError`"""
        tz = get_timezone(tzname)
        if not tz:
            raise KeyError(tzname)
        return tz

    def get_timezone(tzname):
        """Fetch timezone instance by name or return `None`"""
        try:
            # if given unicode parameter, pytz.timezone fails with:
            # "type() argument 1 must be string, not unicode"
            tz = pytz.timezone(to_unicode(tzname).encode('ascii', 'replace'))
        except (KeyError, IOError):
            tz = _tzmap.get(tzname)
        if tz and tzname.startswith('Etc/'):
            tz = _tzoffsetmap.get(tz.utcoffset(None))
        return tz

    _pytz_zones = [tzname for tzname in pytz.common_timezones
                   if not tzname.startswith('Etc/') and
                      not tzname.startswith('GMT')]
    # insert just the GMT timezones into the pytz zones at the right location
    # the pytz zones already include UTC so skip it
    from bisect import bisect
    _gmt_index = bisect(_pytz_zones, 'GMT')
    all_timezones = _pytz_zones[:_gmt_index] + all_timezones[1:] + \
                    _pytz_zones[_gmt_index:]
 
except ImportError:
    pytz = None

    def timezone(tzname):
        """Fetch timezone instance by name or raise `KeyError`"""
        return _tzmap[tzname]

    def get_timezone(tzname):
        """Fetch timezone instance by name or return `None`"""
        return _tzmap.get(tzname)
