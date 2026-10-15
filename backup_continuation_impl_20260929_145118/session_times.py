from datetime import date, datetime, time, timedelta

from django.utils import timezone

from .models import CoverageSession


DAY_START = time(9, 0)
DAY_END = time(21, 0)

NIGHT_START = time(21, 0)
NIGHT_END = time(9, 0)

DAY_AUTO_CLOSE = time(20, 45)
NIGHT_AUTO_CLOSE = time(8, 45)


def get_session_type(moment=None):
    """
    Return the operating session type for a given Nairobi-local moment.

    Day session:   09:00 to 21:00
    Night session:  21:00 to 09:00
    """

    if moment is None:
        moment = timezone.localtime()

    current_time = moment.time()

    if DAY_START <= current_time < DAY_END:
        return CoverageSession.SessionType.DAY

    return CoverageSession.SessionType.NIGHT


def get_operating_date(moment=None, session_type=None):
    """
    Return the operating date associated with the current session.

    Day session:
        09:00 to 21:00 belongs to the current calendar date.

    Night session:
        21:00 to midnight belongs to the current calendar date.
        Midnight to 09:00 belongs to the previous calendar date.
    """

    if moment is None:
        moment = timezone.localtime()

    if session_type is None:
        session_type = get_session_type(moment)

    if session_type == CoverageSession.SessionType.NIGHT:
        if moment.time() < NIGHT_END:
            return moment.date() - timedelta(days=1)

    return moment.date()


def get_scheduled_close_at(moment=None, session_type=None):
    """
    Return the automatic session closure datetime.

    Day coverage closes automatically at 20:45.
    Night coverage closes automatically at 08:45 the following morning.
    """

    if moment is None:
        moment = timezone.localtime()

    if session_type is None:
        session_type = get_session_type(moment)

    operating_date = get_operating_date(moment, session_type)

    if session_type == CoverageSession.SessionType.DAY:
        close_date = operating_date
        close_time = DAY_AUTO_CLOSE
    else:
        close_date = operating_date + timedelta(days=1)
        close_time = NIGHT_AUTO_CLOSE

    naive_datetime = datetime.combine(close_date, close_time)

    return timezone.make_aware(
        naive_datetime,
        timezone.get_current_timezone(),
    )
