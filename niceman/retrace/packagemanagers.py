# emacs: -*- mode: python; py-indent-offset: 4; tab-width: 4; indent-tabs-mode: nil; coding: utf-8 -*-
# ex: set sts=4 ts=4 sw=4 noet:
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the niceman package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
"""Classes to identify package sources for files"""

from __future__ import unicode_literals

import collections
import os
from six import viewvalues
from logging import getLogger
import time
import pytz
from datetime import datetime
try:
    import apt
    cache = apt.Cache()
except ImportError:
    apt = None
    cache = None

from niceman.cmd import Runner
from niceman.cmd import CommandError

lgr = getLogger('niceman.api.retrace')

# Note: The following was derived from ReproZip's PkgManager class
# (Revised BSD License)


class PackageManager(object):
    """Base class for package identifiers."""

    def __init__(self):
        # will be (re)used to run external commands, and let's hardcode LC_ALL
        # codepage just in case since we might want to comprehend error
        # messages
        self._runner = Runner(env={'LC_ALL': 'C'})

    def search_for_files(self, files):
        """Identifies the packages for a given collection of files

        From an iterative collection of files, we identify the packages
        that contain the files and any files that are not related.

        Parameters
        ----------
        files : iterable
            Container (e.g. list or set) of file paths

        Return
        ------
        (found_packages, unknown_files)
            - found_packages is an array of dicts that holds information about
              the found packages. Package dicts need at least "name" and
              "files" (that contains an array of related files)
            - unknown_files is a list of files that were not found in
              a package
        """
        unknown_files = set()
        found_packages = {}
        nb_pkg_files = 0

        for f in files:
            pkgname = self._get_package_for_file(f)

            # Stores the file
            if not pkgname:
                unknown_files.add(f)
            else:
                if pkgname in found_packages:
                    found_packages[pkgname]["files"].append(f)
                    nb_pkg_files += 1
                else:
                    pkg = self._create_package(pkgname)
                    if pkg:
                        found_packages[pkgname] = pkg
                        pkg["files"].append(f)
                        nb_pkg_files += 1
                    else:
                        unknown_files.add(f)

        lgr.info("%d packages with %d files, and %d other files",
                 len(found_packages),
                 nb_pkg_files,
                 len(unknown_files))

        return list(viewvalues(found_packages)), unknown_files

    def identify_package_origins(self, packages):
        """Identify and collate origins from a set of packages

        From a collection of packages, identify the unique origins
        into a separate collection.

        Parameters
        ----------
        packages : iterable
            Array of Package (to be updated)

        Return
        ------
        (origins)
            - Discovered collection of origins
        """
        raise NotImplementedError

    def _get_package_for_file(self, filename):
        raise NotImplementedError

    def _create_package(self, pkgname):
        raise NotImplementedError


class DpkgManager(PackageManager):
    """DPKG Package Identifier
    """

    # TODO: Read in full files from dpkg/info/*.list and .config
    # TODO: (Low Priority) handle cases from dpkg-divert

    def identify_package_origins(self, packages):
        origins = []
        # First, pull out all unique origins
        for p in packages:
            for v in p.get("version_table", []):
                for o in v.get("origins", []):
                    if o not in origins:
                        origins.append(o)

        # Now let's name the origins
        origin_names = []
        origin_name_set = set()
        # Iterate through each origin, creating a name out of the
        # origin and site, and make sure it is unique (by adding a number)
        for o in origins:
            i = 0
            name = "apt_" + o.get("origin") + "_" + o.get("site") + "_" + \
                   o.get("archive") + "_"
            # See if the name is unique (and increment the number until it is)
            while (name + str(i)) in origin_name_set:
                i += 1
            # store the new name into our origin list and set
            origin_name_set.add(name + str(i))
            origin_names.append(name + str(i))

        # Now replace the origins with our created names
        # TODO: replace iterative search with a hash lookup?
        for p in packages:
            for v in p.get("version_table", []):
                for i, o in enumerate(v.get("origins", [])):
                    lookup_idx = origins.index(o)
                    v["origins"][i] = origin_names[lookup_idx]

        # Now update the origins with their name and type
        for i, o in enumerate(origins):
            o["name"] = origin_names[i]
            o["type"] = "apt"

        return origins

    def _get_package_for_file(self, filename):
        try:
            out, err = self._runner.run(
                ['dpkg-query', '-S', filename],
                expect_stderr=True, expect_fail=True
            )
        except CommandError as exc:
            if 'no path found matching pattern' in exc.stderr:
                return None  # no package
            raise  # some other fault -- handle it above

        # Note, we must split after ": " instead of ":" in case the
        # package name includes an architecture (like "zlib1g:amd64")
        try:
            out = out.decode()
        except AttributeError:
            pass
        pkg = out.split(': ', 1)[0]
        lgr.debug("Identified file %r to belong to package %s", filename, pkg)
        return pkg

    def _create_package(self, pkgname):
        if not cache:
            return None
        try:
            pkg_info = cache[pkgname]
        except KeyError:  # Package not found
            return None

        # prep our pkg object:
        pkg = collections.OrderedDict()
        pkg["name"] = pkgname
        pkg["version"] = pkg_info.installed.version
        pkg["candidate"] = pkg_info.candidate.version
        pkg["size"] = pkg_info.installed.size
        pkg["architecture"] = pkg_info.installed.architecture
        pkg["md5"] = pkg_info.installed.md5
        pkg["sha1"] = pkg_info.installed.sha1
        pkg["sha256"] = pkg_info.installed.sha256
        if pkg_info.installed.source_name:
            pkg["source_name"] = pkg_info.installed.source_name
            pkg["source_version"] = pkg_info.installed.source_version
        pkg["files"] = []

        # Now get installation date
        try:
            pkg["install_date"] = str(
                pytz.utc.localize(
                    datetime.utcfromtimestamp(
                        os.path.getmtime(
                            "/var/lib/dpkg/info/" + pkgname + ".list"))))
        except OSError:  # file not found
            pass

        # Compile Version Table
        pkg_versions = []
        for v in pkg_info.versions:
            v_info = {"version": v.version}
            origins = []
            for o in v.origins:
                origins.append({"component": o.component,
                                "archive": o.archive,
                                "origin": o.origin,
                                "label": o.label,
                                "site": o.site})
            v_info["origins"] = origins
            pkg_versions.append(v_info)

        pkg["version_table"] = pkg_versions

        lgr.debug("Found package %s", pkg)
        return pkg


def identify_packages(files):
    """Identify packages files belong to

    Parameters
    ----------
    files : iterable
      Files to consider

    Returns
    -------
    packages : list of Package
    unknown_files : list of str
      Files which were not determined to belong to some package
    """
    manager = DpkgManager()
    begin = time.time()
    (packages, unknown_files) = manager.search_for_files(files)
    origin = manager.identify_package_origins(packages)
    lgr.debug("Assigning files to packages took %f seconds",
              (time.time() - begin))

    return packages, origin, list(unknown_files)
