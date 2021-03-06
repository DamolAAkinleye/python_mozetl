import pytest
import os
from mozetl.schemas import MAIN_SUMMARY_SCHEMA
from mozetl.clientsdaily import rollup as cd


EXPECTED_INTEGER_VALUES = {
    'active_addons_count_mean': 3613,
    'crashes_detected_content_sum': 9,
    'first_paint_mean': 12802105,
    'pings_aggregated_by_this_row': 1122,
    'search_count_all_sum': 1043,
    'scalar_parent_browser_engagement_unique_domains_count_max': 3160,
    'scalar_parent_browser_engagement_unique_domains_count_mean': 2628
}


@pytest.fixture
def main_summary(spark):
    root = os.path.dirname(__file__)
    path = os.path.join(root, 'resources',
                        'main_summary-late-may-1123-rows-anonymized.json')
    frame = spark.read.json(path, MAIN_SUMMARY_SCHEMA)
    return frame


@pytest.fixture
def main_summary_with_search(main_summary):
    return cd.extract_search_counts(main_summary)


@pytest.fixture
def clients_daily(main_summary_with_search):
    return cd.to_profile_day_aggregates(main_summary_with_search)


def test_extract_search_counts(main_summary_with_search):
    row = main_summary_with_search.agg({'search_count_all': 'sum'}).collect()[0]
    total = row.asDict().values()[0]
    assert total == EXPECTED_INTEGER_VALUES['search_count_all_sum']


def test_domains_count(main_summary_with_search):
    unique_domains = 'scalar_parent_browser_engagement_unique_domains_count'
    row = main_summary_with_search.agg({unique_domains: 'sum'}).collect()[0]
    total = row.asDict().values()[0]
    assert total == 4402


def test_to_profile_day_aggregates(clients_daily):
    # Sum up the means and sums as calculated over 1123 rows,
    # one of which is a duplicate.
    aggd = dict([(k, 'sum') for k in EXPECTED_INTEGER_VALUES])
    result = clients_daily.agg(aggd).collect()[0]

    for k, expected in EXPECTED_INTEGER_VALUES.items():
        actual = int(result['sum({})'.format(k)])
        assert actual == expected


def test_profile_creation_date_fields(clients_daily):
    # Spark's from_unixtime() is apparently sensitive to environment TZ
    # See https://issues.apache.org/jira/browse/SPARK-17971
    # There are therefore three possible expected results, depending on
    # the TZ setting of the system on which the tests run.
    expected_back = set([
        u'2014-12-16', u'2016-09-07',
        u'2016-05-12', u'2017-02-16',
        u'2012-11-17', u'2013-09-08',
        u'2017-02-12', u'2016-04-04',
        u'2017-04-25', u'2015-06-17'
    ])
    expected_utc = set([
        u'2014-12-17', u'2016-09-08',
        u'2016-05-13', u'2017-02-17',
        u'2012-11-18', u'2013-09-09',
        u'2017-02-13', u'2016-04-05',
        u'2017-04-26', u'2015-06-18'
    ])
    expected_forward = set([
        u'2014-12-18', u'2016-09-09',
        u'2016-05-14', u'2017-02-18',
        u'2012-11-19', u'2013-09-10',
        u'2017-02-14', u'2016-04-06',
        u'2017-04-27', u'2015-06-19'
    ])
    ten_pcds = clients_daily.select("profile_creation_date").take(10)
    actual1 = set([r.asDict().values()[0][:10] for r in ten_pcds])
    assert actual1 in (expected_back, expected_utc, expected_forward)

    expected2_back = [
        378, 894, 261, 1361, 101, 1656, 415, 29, 703, 102
    ]
    expected2_utc = [
        377, 893, 260, 1360, 100, 1655, 414, 28, 702, 101
    ]
    expected2_forward = [
        376, 892, 259, 1359, 99, 1654, 413, 27, 701, 100
    ]
    ten_pdas = clients_daily.select("profile_age_in_days").take(10)
    actual2 = [r.asDict().values()[0] for r in ten_pdas]
    assert actual2 in (expected2_back, expected2_utc, expected2_forward)


def test_sessions_started_on_this_day(clients_daily):
    expected = [2, 0, 3, 2, 1, 0, 1, 0, 0, 3]
    ten_ssotds = clients_daily.select("sessions_started_on_this_day").take(10)
    actual = [r.asDict().values()[0] for r in ten_ssotds]
    assert actual == expected


# Similar to the test above, but a little easier to compare with
# the source data.
def test_sessions_started_on_this_day_sorted(clients_daily):
    expected = [1, 5, 1, 1, 1, 0, 0, 0, 0, 0]
    one_day = clients_daily.where("activity_date == '2017-05-25'").orderBy("client_id")
    ten_ssotds = one_day.select("sessions_started_on_this_day").take(10)
    actual = [r.asDict().values()[0] for r in ten_ssotds]
    assert actual == expected


# Ensure that "first" aggregations skip null values
def test_first_skips_nulls(clients_daily):
    filter_template = "client_id = '{}' and activity_date = '{}'"
    client = '0c495fce-5fbf-4f4a-ac03-2dedcef0a8d0'
    day = '2017-05-25'
    filter_clause = filter_template.format(client, day)
    null_to_false = clients_daily.where(filter_clause).select("sync_configured").first()
    expected = False
    actual = null_to_false.sync_configured
    assert actual == expected

    expected = 230
    actual = clients_daily.where("sync_configured is null").count()
    assert actual == expected
