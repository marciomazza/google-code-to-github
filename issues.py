import getpass
import itertools
from datetime import datetime

import gdata.projecthosting.client


class Bunch:
    "http://code.activestate.com/recipes/52308-the-simple-but-handy-collector-of-a-bunch-of-named"

    def __init__(self, **kwds):
        self.__dict__.update(kwds)

    def __repr__(self):
        return self.__dict__.__repr__()

class Issue(Bunch):
    pass

def step_queries(max_query_results):
    for start_index in itertools.count(start=1, step=max_query_results):
        yield gdata.projecthosting.client.Query(
            start_index = start_index,
            max_results = max_query_results)

class GoogleCodeProject(object):

    max_query_results = 25

    def __init__(self, name, email=None, password=None):
        """
        Arguments:
        - `name`: Google Code project name
        """
        self.name = name
        self.client = gdata.projecthosting.client.ProjectHostingClient()
        if email:
            password = password or getpass.getpass("Type the google password for %s" % email)
            self.client.client_login(email, password, 'migration')

    def issues(self):
        for query in step_queries(self.max_query_results):
            feed = self.client.get_issues(self.name, query = query)
            if feed.entry:
                for issue in feed.entry:
                    yield Issue(
                        id = int(issue.id.text.split('/')[-1]),
                        status = issue.status.text.lower() if issue.status else None,
                        title = issue.title.text,
                        link = issue.link[1].href,
                        authors = [a.name.text for a in issue.author],
                        content = issue.content.text,
                        date = datetime.strptime(
                            issue.published.text, "%Y-%m-%dT%H:%M:%S.000Z"),
                        labels = [l.text for l in issue.label],
                        owner = issue.owner.username.text if issue.owner else None,
                        feed_entry = issue,
                        )
            else:
                break

