import getpass
import itertools
import os
import re
import subprocess
import tempfile
from datetime import datetime
from urlparse import parse_qs, urlparse

import gdata.projecthosting.client
import requests
from gdata.projecthosting.client import Query
from lxml import html


class Bunch(object):
    "http://code.activestate.com/recipes/52308-the-simple-but-handy-collector-of-a-bunch-of-named"

    def __init__(self, **kwds):
        self.__dict__.update(kwds)

    def __repr__(self):
        return self.__dict__.__repr__()

RE_FILENAME = re.compile('filename="(.+)"$')

class Attachment(object):

    def __init__(self, issue, node):
        self.issue = issue
        self.node = node
        self.url = next(a.attrib['href'] for a in node.cssselect('a')
                        if a.text == 'Download')
        # google code has download urls starting with "//"
        if self.url.startswith('//'):
            self.url = 'http:' + self.url
        parent = node.getparent()
        if 'issuedescription' in parent.attrib['class']:
            # zero for an attachment in the description
            self.place = 0
        elif 'issuecomment' in parent.attrib['class']:
            comment_id =int(re.search(r'\d+$',
                                      parent.attrib['id']).group())
            self.place = comment_id
        else:
            raise AssertionError('Unrecognized attachment %s' % node)

    @property
    def name(self):
        return 'Issue_%s_%s' % (
            self.issue.id,
            parse_qs(urlparse(self.url).query)['name'][0])

    @property
    def description(self):
        return 'Attachment from issue [%d] of google code project %s (original url: %s)' % (
            self.issue.id,
            self.issue.project.name,
            self.url)

    def download(self):
        req = requests.get(self.url)
        return Bunch(
            size=int(req.headers['content-length']),
            content_type=req.headers['content-type'],
            content = req.content,)

    def __repr__(self):
        d = self.__dict__.copy()
        del d['node']
        return d.__repr__()


class Issue(object):

    def __init__(self, project, feed_entry):
        self.project = project
        self.feed_entry = feed_entry
        self.id = int(feed_entry.id.text.split('/')[-1])
        self.status = feed_entry.status.text.lower() if feed_entry.status else None
        self.title = feed_entry.title.text
        self.url = feed_entry.link[1].href
        self.authors = [a.name.text for a in feed_entry.author]
        self.content = feed_entry.content.text
        self.date = datetime.strptime(
            feed_entry.published.text, "%Y-%m-%dT%H:%M:%S.000Z")
        self.labels = [l.text for l in feed_entry.label]
        self.owner = feed_entry.owner.username.text if feed_entry.owner else None

    def attachments(self, place=None):
        '''place: 0 for attachments in the description,
                  N for attachments in comment N
        '''
        if not hasattr(self, '_attachments'):
            scrap = html.parse(self.url).getroot()
            self._attachments = [Attachment(self, node)
                                 for node in scrap.cssselect('.attachments')]
        if place is None:
            return self._attachments
        else:
            return [a for a in self._attachments if a.place == place]


class GoogleCodeProject(object):

    max_query_results = 25

    def __init__(self, name, email=None, password=None):
        """
        Arguments:
        - `name`: Google Code project name
        - `email`: login email, if you want to log in (optional)
        - `name` : login password (optional)
        """
        self.name = name
        self.client = gdata.projecthosting.client.ProjectHostingClient()
        if email:
            password = password or getpass.getpass("Type the google password for %s" % email)
            self.client.client_login(email, password, 'migration')

    def get_issues(self, query=None):
        if query:
            queries = [query]
        else:
            queries = (Query(start_index = start_index,
                             max_results = self.max_query_results)
                       for start_index in
                       itertools.count(start=1, step=self.max_query_results))
        for query in queries:
            feed = self.client.get_issues(self.name, query = query)
            if feed.entry:
                for entry in feed.entry:
                    yield Issue(self, entry)
            else:
                break

    def get_issue_by_id(self, issue_id):
        issues = list(self.get_issues(Query(issue_id=issue_id)))
        return issues[0] if issues else None

class GithubMigrator(object):

    def __init__(self, repo):
        """
        Arguments:
        - `repo`: a github.Repository.Repository to migrate to
        """
        self.repo = repo

    def upload_attachment(self, attachment):
        download = attachment.download()
        res = self.repo.create_download(name=attachment.name,
                                        description=attachment.description,
                                        size=download.size,
                                        content_type=download.content_type,)
        # there should be a better way to do this, but I couldn't
        # good enough is the new black
        # see http://developer.github.com/v3/repos/downloads/#create-a-new-download-part-2-upload-file-to-s3
        with tempfile.NamedTemporaryFile(delete=False) as download_file:
            download_file.write(download.content)
        subp = subprocess.Popen(['curl',
        '-F', 'key=' + res.path,
        '-F', 'acl=' + res.acl,
        '-F', 'success_action_status=201',
        '-F', 'Filename=' + res.name,
        '-F', 'AWSAccessKeyId=' + res.accesskeyid,
        '-F', 'Policy=' + res.policy,
        '-F', 'Signature=' + res.signature,
        '-F', 'Content-Type=' + res.mime_type,
        '-F', 'file=@' + download_file.name,
        'https://github.s3.amazonaws.com/'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        curlstdout, curlstderr = subp.communicate()
        os.remove(download_file.name)
        return 'https://github.com/' + res.path
