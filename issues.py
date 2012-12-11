import getpass
import itertools
import os
import re
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime
from urlparse import parse_qs, urlparse

import gdata.projecthosting.client
import requests
from gdata.projecthosting.client import Query
from lxml import html


class SimpleRepr(object):

    def __repr__(self):
        return self.__dict__.__repr__()

# based on http://getpython3.com/diveintopython3/examples/humansize.py
def human_readable_size(size):
    if size < 0:
        raise ValueError('number must be non-negative')
    size = float(size)
    for suffix in ['KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB']:
        size /= 1000
        if size < 1000:
            return '{0:.1f} {1}'.format(size, suffix)
    raise ValueError('number too large')


class Download(SimpleRepr):

    RE_FILENAME = re.compile('filename="(.+)"$')

    def __init__(self, attachment):
        req = requests.get(attachment.url)
        assert attachment.original_name == self.RE_FILENAME.search(
            req.headers['content-disposition']).group(1)
        self.size = int(req.headers['content-length'])
        self.content_type = req.headers['content-type']
        self.content = req.content


class Attachment(object):

    DESCRIPTION_PLACE = 0

    def __init__(self, issue, node):
        self.issue = issue
        self.node = node
        self.url = next(a.attrib['href'] for a in node.cssselect('a')
                        if a.text == 'Download')
        # google code has download urls starting with "//"
        if self.url.startswith('//'):
            self.url = 'http:' + self.url
        # classify by place of occurrence
        # 0 for an attachment in the description,
        # N for an attachment in comment N
        parent = node.getparent()
        if 'issuedescription' in parent.attrib['class']:
            # zero for an attachment in the description
            self.place = Attachment.DESCRIPTION_PLACE
        elif 'issuecomment' in parent.attrib['class']:
            comment_id =int(re.search(r'\d+$',
                                      parent.attrib['id']).group())
            self.place = comment_id
        else:
            raise AssertionError('Unrecognized attachment %s' % node)

    @property
    def original_name(self):
        return parse_qs(urlparse(self.url).query)['name'][0]

    @property
    def name(self):
        return 'Issue_%s_%s' % (self.issue.id, self.original_name)

    @property
    def description(self):
        return 'Attachment from issue [%d] of google code project %s (original url: %s)' % (
            self.issue.id, self.issue.project.name, self.url)

    def download(self):
        download = Download(self)
        self._size = download.size
        return download

    @property
    def human_readable_size(self):
        if not hasattr(self, '_size'):
            self.download()
        return human_readable_size(self._size)

    def __repr__(self):
        d = self.__dict__.copy()
        del d['node']
        return d.__repr__()

def _init_common_fields(self, feed_entry, link_index_for_url):
    self.feed_entry = feed_entry
    self.id = int(feed_entry.id.text.split('/')[-1])
    self.title = feed_entry.title.text
    self.url = feed_entry.link[link_index_for_url].href
    self.author = feed_entry.author[0].name.text
    self.content = feed_entry.content.text
    self.date = datetime.strptime(feed_entry.published.text, "%Y-%m-%dT%H:%M:%S.000Z")


class Issue(SimpleRepr):

    def __init__(self, project, feed_entry):
        _init_common_fields(self, feed_entry, 1)
        self.project = project
        self.status = feed_entry.status.text.lower() if feed_entry.status else None
        self.labels = [l.text for l in feed_entry.label]
        self.owner = feed_entry.owner.username.text if feed_entry.owner else None

    @property
    def all_attachments_by_place(self):
        if not hasattr(self, '_all_attachments_by_place'):
            scrap = html.parse(self.url).getroot()
            self._all_attachments_by_place = defaultdict(list)
            for node in scrap.cssselect('.attachments'):
                att = Attachment(self, node)
                self._all_attachments_by_place[att.place].append(att)
        return self._all_attachments_by_place

    @property
    def attachments(self):
        '''Attachments only in the description, i.e., not in comments'''
        return self.all_attachments_by_place[Attachment.DESCRIPTION_PLACE]

    @property
    def comments(self):
        if not hasattr(self, '_comments'):
            self._comments = list(self.project.get_comments(self))
        return self._comments


class Comment(SimpleRepr):

    def __init__(self, issue, feed_entry):
        _init_common_fields(self, feed_entry, 0)
        self.issue = issue

    @property
    def attachments(self):
        return self.issue.all_attachments_by_place[self.id]


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

    def get_issues(self, specific_query=None):
        return self._get_items(
            lambda query: self.client.get_issues(self.name, query = query),
            lambda entry: Issue(self, entry),
            specific_query)

    def get_comments(self, issue, specific_query=None):
        return self._get_items(
            lambda query: self.client.get_comments(self.name, issue.id, query = query),
            lambda entry: Comment(issue, entry),
            specific_query)

    def _get_items(self, query_to_feed, entry_to_item, specific_query=None):
        if specific_query:
            queries = [specific_query]
        else:
            # fetch N entries, first starting from 1, then from 1+N, 1+2N, ...
            queries = (Query(start_index = start_index,
                             max_results = self.max_query_results)
                       for start_index in
                       itertools.count(start=1, step=self.max_query_results))
        for query in queries:
            feed = query_to_feed(query)
            if feed.entry:
                for entry in feed.entry:
                    yield entry_to_item(entry)
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
                                 'https://github.s3.amazonaws.com/'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        curlstdout, curlstderr = subp.communicate()
        os.remove(download_file.name)
        return 'https://github.com/' + res.path


