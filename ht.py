#!/usr/bin/env python

"""t is for people that want do things, not organize their tasks."""

from __future__ import with_statement

import os, re, sys, hashlib, datetime
from operator import itemgetter
from optparse import OptionParser, OptionGroup
from pyrise import *


class InvalidTaskfile(Exception):
    """Raised when the path to a task file already exists as a directory."""
    pass

class AmbiguousPrefix(Exception):
    """Raised when trying to use a prefix that could identify multiple tasks."""
    def __init__(self, prefix):
        super(AmbiguousPrefix, self).__init__()
        self.prefix = prefix

class UnknownPrefix(Exception):
    """Raised when trying to use a prefix that does not match any tasks."""
    def __init__(self, prefix):
        super(UnknownPrefix, self).__init__()
        self.prefix = prefix


def _hash(text):
    """Return a hash of the given text for use as an id.

    Currently SHA1 hashing is used.  It should be plenty for our purposes.

    """
    return hashlib.sha1(str(text)).hexdigest()

def _prefixes(ids):
    """Return a mapping of ids to prefixes in O(n) time.

    Each prefix will be the shortest possible substring of the ID that
    can uniquely identify it among the given group of IDs.

    If an ID of one task is entirely a substring of another task's ID, the
    entire ID will be the prefix.
    """
    ps = {}
    for id in ids.keys():
        id1 = _hash(id)
        id_len = len(id1)
        for i in range(1, id_len+1):
            # identifies an empty prefix slot, or a singular collision
            prefix = id1[:i]
            if (not prefix in ps) or (ps[prefix] and prefix != ps[prefix]):
                break
        if prefix in ps:
            # if there is a collision
            other_id = ps[prefix]
            other_id1 = _hash(ps[prefix])
            for j in range(i, id_len+1):
                if other_id1[:j] == id1[:j]:
                    ps[id1[:j]] = ''
                else:
                    ps[other_id1[:j]] = other_id
                    ps[id1[:j]] = id
                    break
            else:
                ps[other_id1[:id_len+1]] = other_id
                ps[id1] = id
        else:
            # no collision, can safely add
            ps[prefix] = id
    ps = dict(zip(ps.values(), ps.keys()))
    if '' in ps:
        del ps['']
    return ps


class TaskDict(object):
    """A set of tasks, both finished and unfinished, for a given list.

    The list's files are read from disk when the TaskDict is initialized. They
    can be written back out to disk with the write() function.

    """
    def __init__(self, name='tasks'):
        """Initialize by reading the task files, if they exist."""
        self.tasks = {} 
        self.done = {}
        self.prefixes = {}
        self.name = name
        if 'HIGHRISE_SITE' and 'HIGHRISE_API_KEY' in os.environ:
            Highrise.set_server(os.environ['HIGHRISE_SITE'])
            Highrise.auth(os.environ['HIGHRISE_API_KEY'])
        else:
            sys.stderr.write('Highrise credentials not found. Set HIGHRISE_SITE and HIGHRISE_API_KEY environment variables.\n')     
            sys.exit()
        tasks = Task().all()
        for task in tasks:
            self.tasks[task.id] = task
            self.prefixes[task.id] = ''
        for task_id, prefix in _prefixes(self.prefixes).items():
            self.prefixes[task_id] = prefix


    def __getitem__(self, prefix):
        """Return the unfinished task with the given prefix.

        If more than one task matches the prefix an AmbiguousPrefix exception
        will be raised, unless the prefix is the entire ID of one task.

        If no tasks match the prefix an UnknownPrefix exception will be raised.

        """
        matched = filter(lambda tid: tid.startswith(prefix), self.tasks.keys())
        if len(matched) == 1:
            return self.tasks[matched[0]]
        elif len(matched) == 0:
            raise UnknownPrefix(prefix)
        else:
            matched = filter(lambda tid: tid == prefix, self.tasks.keys())
            if len(matched) == 1:
                return self.tasks[matched[0]]
            else:
                raise AmbiguousPrefix(prefix)

    def add_task(self, text):
        """Add a new, unfinished task with the given summary text."""
        task_id = _hash(text)
        self.tasks[task_id] = {'id': task_id, 'text': text}

    def edit_task(self, prefix, text):
        """Edit the task with the given prefix.

        If more than one task matches the prefix an AmbiguousPrefix exception
        will be raised, unless the prefix is the entire ID of one task.

        If no tasks match the prefix an UnknownPrefix exception will be raised.

        """
        task = self[prefix]
        if text.startswith('s/') or text.startswith('/'):
            text = re.sub('^s?/', '', text).rstrip('/')
            find, _, repl = text.partition('/')
            text = re.sub(find, repl, task['text'])

        task['text'] = text

    def finish_task(self, prefix):
        """Mark the task with the given prefix as finished.

        If more than one task matches the prefix an AmbiguousPrefix exception
        will be raised, if no tasks match it an UnknownPrefix exception will
        be raised.

        """
        for item in self.prefixes.items():
            if item[1] == prefix:
                task_id = item[0]
                break
        if not task_id:
            print 'Task with prefix "%s" not found!' % prefix
            exit
        task = self.tasks[task_id]
        task.done_at = datetime.utcnow()
        task.save()

    def remove_task(self, prefix):
        """Remove the task from tasks list.

        If more than one task matches the prefix an AmbiguousPrefix exception
        will be raised, if no tasks match it an UnknownPrefix exception will
        be raised.

        """
        self.tasks.pop(self[prefix]['id'])


    def print_list(self, kind='tasks', verbose=False, quiet=False, grep=''):
        """Print out a nicely formatted list of unfinished tasks."""
        tasks = dict(getattr(self, kind).items())
        plen = 0

        if not verbose:
            plen = max(map(lambda t: len(t), self.prefixes.values())) 
        for _, task in sorted(tasks.items()):
            if grep.lower() in task.body.lower():
                p = '%s - ' % self.prefixes[task.id].ljust(plen) if not quiet else ''
                print p + task.body

    def write(self, delete_if_empty=False):
        """Flush the finished and unfinished tasks to the files on disk."""
        filemap = (('tasks', self.name), ('done', '.%s.done' % self.name))
        for kind, filename in filemap:
            path = os.path.join(os.path.expanduser(self.taskdir), filename)
            if os.path.isdir(path):
                raise InvalidTaskfile
            tasks = sorted(getattr(self, kind).values(), key=itemgetter('id'))
            if tasks or not delete_if_empty:
                with open(path, 'w') as tfile:
                    for taskline in _tasklines_from_tasks(tasks):
                        tfile.write(taskline)
            elif not tasks and os.path.isfile(path):
                os.remove(path)


def _build_parser():
    """Return a parser for the command-line interface."""
    usage = "Usage: %prog [-l LIST] [options] [TEXT]"
    parser = OptionParser(usage=usage)

    actions = OptionGroup(parser, "Actions",
        "If no actions are specified the TEXT will be added as a new task.")
    actions.add_option("-e", "--edit", dest="edit", default="",
                       help="edit TASK to contain TEXT", metavar="TASK")
    actions.add_option("-f", "--finish", dest="finish",
                       help="mark TASK as finished", metavar="TASK")
    actions.add_option("-r", "--remove", dest="remove",
                       help="Remove TASK from list", metavar="TASK")
    parser.add_option_group(actions)

    config = OptionGroup(parser, "Configuration Options")
    config.add_option("-l", "--list", dest="name", default="tasks",
                      help="work on LIST", metavar="LIST")
    parser.add_option_group(config)

    output = OptionGroup(parser, "Output Options")
    output.add_option("-g", "--grep", dest="grep", default='',
                      help="print only tasks that contain WORD", metavar="WORD")
    output.add_option("-v", "--verbose",
                      action="store_true", dest="verbose", default=False,
                      help="print more detailed output (full task ids, etc)")
    output.add_option("-q", "--quiet",
                      action="store_true", dest="quiet", default=False,
                      help="print less detailed output (no task ids, etc)")
    output.add_option("--done",
                      action="store_true", dest="done", default=False,
                      help="list done tasks instead of unfinished ones")
    parser.add_option_group(output)

    return parser

def _main():
    """Run the command-line interface."""
    (options, args) = _build_parser().parse_args()

    td = TaskDict(name=options.name)
    text = ' '.join(args).strip()

    try:
        if options.finish:
            td.finish_task(options.finish)
        elif options.remove:
            td.remove_task(options.remove)
        elif options.edit:
            td.edit_task(options.edit, text)
        elif text:
            td.add_task(text)
        else:
            kind = 'tasks' if not options.done else 'done'
            td.print_list(kind=kind, verbose=options.verbose, quiet=options.quiet,
                          grep=options.grep)
    except AmbiguousPrefix, e:
        sys.stderr.write('The ID "%s" matches more than one task.\n' % e.prefix)
    except UnknownPrefix, e:
        sys.stderr.write('The ID "%s" does not match any task.\n' % e.prefix)


if __name__ == '__main__':
    _main()
