"""The netdisk pipeline (devtools/netdisk/): which release is published, what every netdisk does with it, and
that one netdisk's trouble never holds the others back."""
import json
import platform
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from devtools.netdisk import Asset, Outcome, Target, TargetError, TargetUnavailable   # noqa: E402
from devtools.netdisk import pipeline, release                                         # noqa: E402
from devtools.netdisk.targets import quark                                             # noqa: E402


class Tool(unittest.TestCase):
    """The tool the netdisks drive"""

    def test_the_machine_is_named_the_way_the_release_names_it(self):
        """the runner calls its cpu x86_64, the release calls it amd64"""
        for machine, build in (('x86_64', 'amd64'), ('amd64', 'amd64'),
                               ('aarch64', 'arm64'), ('arm64', 'arm64')):
            original = platform.machine
            platform.machine = lambda m=machine: m
            try:
                self.assertEqual(quark._machine(), build)
            finally:
                platform.machine = original

    def test_a_machine_the_release_has_no_build_for_has_none(self):
        original = platform.machine
        platform.machine = lambda: 'risc-v'
        try:
            self.assertEqual(quark.build_for_this_machine(), '')
        finally:
            platform.machine = original


class LatestRelease(unittest.TestCase):
    """Which release is published"""

    def test_the_latest_release_is_the_one_that_was_cut_last(self):
        answer = [{'tag_name': 'v0.4.1-alpha02', 'draft': False,
                   'assets': [{'name': 'nx2android-v0.4.1-alpha02.apk', 'size': 273313264,
                               'digest': 'sha256:abc'}, {'name': 'nx2a-profiles-r1-bf1e4edd.zip', 'size': 96160472}]}]
        original = release.gh
        release.gh = lambda args, timeout=None: json.dumps(answer)
        try:
            r = release.latest()
        finally:
            release.gh = original
        self.assertEqual(r.tag, 'v0.4.1-alpha02')
        self.assertEqual([a.name for a in r.assets],
                         ['nx2android-v0.4.1-alpha02.apk', 'nx2a-profiles-r1-bf1e4edd.zip'])
        self.assertEqual(r.assets[0].digest, 'sha256:abc')

    def test_a_draft_is_not_a_release(self):
        original = release.gh
        release.gh = lambda args, timeout=None: json.dumps([{'tag_name': 'v9', 'draft': True}])
        try:
            with self.assertRaises(release.ReleaseError):
                release.latest()
        finally:
            release.gh = original

    def test_a_release_that_carries_nothing_is_told_so(self):
        original = release.gh
        release.gh = lambda args, timeout=None: json.dumps([{'tag_name': 'v1', 'draft': False, 'assets': []}])
        try:
            with self.assertRaises(release.ReleaseError):
                pipeline.publish(out=lambda m: None)
        finally:
            release.gh = original

    def test_a_file_that_is_not_what_the_release_says_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.apk'
            path.write_bytes(b'not the file')
            asset = Asset(name='a.apk', size=9, digest='sha256:' + '0' * 64)
            with self.assertRaises(release.ReleaseError):
                release.check_digest(asset, path)

    def test_the_file_the_release_names_is_the_file_that_is_there(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.apk'
            path.write_bytes(b'the file')
            digest = hashlib.sha256(b'the file').hexdigest()
            release.check_digest(Asset(name='a.apk', digest='sha256:' + digest), path)


class FakeTarget(Target):
    """A netdisk in the test: it can go on, it can be without a cookie, or it can fall over."""

    def __init__(self, name, state='ok'):
        self.name = name
        self.state = state
        self.published = []

    def prepare(self):
        if self.state == 'no-cookie':
            raise TargetUnavailable('the cookie is missing')
        if self.state == 'no-tool':
            raise TargetError('the tool is not there')

    def publish(self, assets):
        if self.state == 'refused':
            raise TargetError('the cookie was refused')
        self.published = [a.name for a in assets]
        return [Outcome(a.name, 'uploaded', '') for a in assets]


class WaitingForTheFiles(unittest.TestCase):
    """A release is published before the build that its tag started attaches the files"""

    def test_a_release_that_carries_the_apk_is_not_waited_for(self):
        r = release.Release('v1', [Asset(name='nx2android-v1.apk', size=1)])
        original = release.by_tag
        release.by_tag = lambda repo, tag: r
        try:
            self.assertIs(release.wait_for_assets('r/r', r, timeout=1), r)
        finally:
            release.by_tag = original

    def test_the_wait_ends_when_the_apk_is_there_and_the_files_stop_changing(self):
        empty = release.Release('v1', [])
        with_apk = release.Release('v1', [Asset(name='nx2android-v1.apk', size=1),
                                          Asset(name='nx2a-profiles-r1-abcdef12.zip', size=2)])
        answers = [empty, with_apk, with_apk]
        original, original_sleep = release.by_tag, time.sleep
        release.by_tag = lambda repo, tag: answers.pop(0)
        time.sleep = lambda seconds: None
        try:
            got = release.wait_for_assets('r/r', empty, timeout=60, every=1)
        finally:
            release.by_tag, time.sleep = original, original_sleep
        self.assertEqual([a.name for a in got.assets],
                         ['nx2android-v1.apk', 'nx2a-profiles-r1-abcdef12.zip'])

    def test_a_release_without_an_apk_is_not_published(self):
        original = release.gh
        release.gh = lambda args, timeout=None: json.dumps([{'tag_name': 'v1', 'draft': False,
                                                              'assets': [{'name': 'nx2a-profiles.zip', 'size': 1}]}])
        try:
            with self.assertRaises(release.ReleaseError) as caught:
                pipeline.publish(out=lambda m: None)
            self.assertIn('no APK', str(caught.exception))
        finally:
            release.gh = original


class Pipeline(unittest.TestCase):
    """The fan-out"""

    def _assets(self):
        return [Asset(name='nx2android-v1.apk', size=1)]

    def test_one_netdisk_that_falls_over_does_not_hold_the_others_back(self):
        good = FakeTarget('good')
        broken = FakeTarget('broken', 'refused')
        without = FakeTarget('without', 'no-cookie')
        ready, failed = pipeline.prepare([good, broken, without], out=lambda m: None)
        self.assertEqual([t.name for t in ready], ['good', 'broken'])
        self.assertEqual(failed, 0)
        results = pipeline.run(ready, self._assets(), out=lambda m: None)
        states = {r.name: r.state for r in results}
        self.assertEqual(states, {'good': 'ok', 'broken': 'failed'})
        self.assertEqual(good.published, ['nx2android-v1.apk'])

    def test_a_netdisk_without_a_cookie_is_skipped_and_the_others_still_go(self):
        good = FakeTarget('good')
        without = FakeTarget('without', 'no-cookie')
        ready, failed = pipeline.prepare([good, without], out=lambda m: None)
        self.assertEqual([t.name for t in ready], ['good'])
        self.assertEqual(failed, 0)

    def test_a_netdisk_without_a_tool_is_a_failure_and_not_a_skip(self):
        ready, failed = pipeline.prepare([FakeTarget('x', 'no-tool')], out=lambda m: None)
        self.assertEqual(ready, [])
        self.assertEqual(failed, 1)

    def test_the_exit_code_tells_whether_every_netdisk_went_well(self):
        assets = [Asset(name='nx2android-v1.apk', size=1)]

        def fake_latest(repo):
            return release.Release('v1', assets)

        original_latest, original_fetch = release.latest, release.fetch
        release.latest = fake_latest
        release.fetch = lambda repo, rel, dest: rel.assets
        try:
            code = pipeline.publish(targets=['a', 'b'], out=lambda m: None,
                                    make=lambda name: FakeTarget(name, 'refused' if name == 'b' else 'ok'))
            self.assertEqual(code, 1)
            code = pipeline.publish(targets=['a'], out=lambda m: None, make=lambda name: FakeTarget(name))
            self.assertEqual(code, 0)
        finally:
            release.latest, release.fetch = original_latest, original_fetch


if __name__ == '__main__':
    unittest.main()
