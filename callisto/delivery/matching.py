import logging

from callisto.evaluation.models import EvalRow
from callisto.notification.api import NotificationApi

from .models import MatchReport

logger = logging.getLogger(__name__)


def run_matching(identifiers=None, notifier=NotificationApi):
    """Compares existing match records to see if any match the given identifiers. If no identifiers are given, checks
    existing match records against identifiers from records that weren't been marked as "seen" the last time matching
    was run. For each identifier for which a new match is found, a report is sent to the receiving authority and the
    reporting users are notified.

    Args:
      identifiers(list of strings, optional): the new identifiers to check for matches, or None if the value is to be
        queried from the DB (Default value = None)
      notifier(notification generator class, optional): Must have `send_matching_report_to_school` method. (Default
      value = NotificationApi)
    """
    logger.info("running matching")
    if identifiers is None:
        identifiers = [match_report.identifier for match_report in MatchReport.objects.filter(seen=False)]
    find_matches(identifiers, notifier=notifier)


def find_matches(identifiers, notifier=NotificationApi):
    """Finds sets of matching records that haven't been identified yet. For a match to count as new, there must be
    associated Reports from at least 2 different users and at least one MatchReport must be newly created since we last
    checked for matches.

    Args:
      identifiers (list of str): the new identifiers to check for matches
      notifier(report generator class, optional): Must have `send_matching_report_to_school` method. (Default
      value = NotificationApi)
    """
    for identifier in identifiers:
        match_list = [potential for potential in MatchReport.objects.all() if potential.get_match(identifier)]
        if len(match_list) > 1:
            seen_match_owners = [match.report.owner for match in match_list if match.seen]
            new_match_owners = [match.report.owner for match in match_list if not match.seen]
            # filter out multiple reports made by the same person
            if len(set(seen_match_owners + new_match_owners)) > 1:
                # only send notifications if new matches are submitted by owners we don't know about
                if not set(new_match_owners).issubset(set(seen_match_owners)):
                    process_new_matches(match_list, identifier, notifier)
                for match_report in match_list:
                    match_report.report.match_found = True
                    match_report.report.save()
        for match in match_list:
            match.seen = True
            # delete identifier, which should only be filled for newly added match reports in delayed matching case
            match.identifier = None
            match.save()


def process_new_matches(matches, identifier, notifier):
    """Sends a report to the receiving authority and notifies the reporting users. Each user should only be notified
    one time when a match is found.

    Args:
      matches (list of MatchReports): the MatchReports that correspond to this identifier
      identifier (str): identifier associated with the MatchReports
      notifier(report generator class, optional): Must have `send_matching_report_to_school` method. (Default
      value = NotificationApi)
    """
    logger.info("new match found")
    owners_notified = []
    for match_report in matches:
        EvalRow.store_eval_row(action=EvalRow.MATCH_FOUND, report=match_report.report)
        owner = match_report.report.owner
        # only send notification emails to new matches
        if owner not in owners_notified and not match_report.report.match_found \
                and not match_report.report.submitted_to_school:
            NotificationApi.send_match_notification(owner, match_report)
            owners_notified.append(owner)
    # send report to school
    notifier.send_matching_report_to_school(matches, identifier)
