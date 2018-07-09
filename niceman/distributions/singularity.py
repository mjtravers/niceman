# emacs: -*- mode: python; py-indent-offset: 4; tab-width: 4; indent-tabs-mode: nil -*-
# ex: set sts=4 ts=4 sw=4 noet:
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the niceman package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
"""Support for Singularity distribution(s)."""

import attr
import json
import logging

lgr = logging.getLogger('niceman.distributions.singularity')

from .base import Package
from .base import Distribution
from .base import DistributionTracer
from .base import TypedList
from .base import _register_with_representer
from ..dochelpers import borrowdoc
from ..utils import attrib, md5sum


@attr.s(slots=True, frozen=True, cmp=False, hash=True)
class SingularityImage(Package):
    """Singularity image information"""
    md5 = attrib(default=attr.NOTHING)
    # Optional
    bootstrap = attrib()
    maintainer = attrib()
    deffile = attrib()
    schema_version = attrib()
    build_date = attrib()
    build_size = attrib()
    singularity_version = attrib()
    base_image = attrib()

_register_with_representer(SingularityImage)


@attr.s
class SingularityDistribution(Distribution):
    """
    Class to provide commands to Singularity.
    """

    images = TypedList(SingularityImage)

    def initiate(self, session):
        """
        Perform any initialization commands needed in the environment
        environment.

        Parameters
        ----------
        session : object
            The Session to work in
        """

        # Raise niceman.support.exceptions.CommandError exception if
        # Singularity is not to be found.
        session.execute_command(['singularity', 'selftest'])

    def install_packages(self, session):
        """
        Install the Singularity images associated to this distribution by the
        provenance into the environment.

        Parameters
        ----------
        session : object
            Session to work in
        """

        # TODO: Currently we have no way to locate the image given the metadata

_register_with_representer(SingularityDistribution)


class SingularityTracer(DistributionTracer):
    """Singularity image tracer

    If a given file is not identified as a singularity image, the files
    are quietly passed on to the next tracer.
    """

    HANDLES_DIRS = False

    @borrowdoc(DistributionTracer)
    def identify_distributions(self, files):
        if not files:
            return

        images = []
        remaining_files = set()

        for file in files:
            try:
                # import pdb; pdb.set_trace()
                image = json.loads(self._session.execute_command(['singularity',
                    'inspect', file])[0])

                images.append(SingularityImage(
                    md5=md5sum(file),
                    bootstrap=image['org.label-schema.usage.singularity.deffile.bootstrap'],
                    maintainer=image['MAINTAINER'],
                    deffile=image['org.label-schema.usage.singularity.deffile'],
                    schema_version=image['org.label-schema.schema-version'],
                    build_date=image['org.label-schema.build-date'],
                    build_size=image['org.label-schema.build-size'],
                    singularity_version=image['org.label-schema.usage.singularity.version'],
                    base_image=image['org.label-schema.usage.singularity.deffile.from']
                ))
            except Exception as exc:
                lgr.debug(exc)
                remaining_files.add(file)

        if not images:
            return

        dist = SingularityDistribution(
            name="singularity",
            images=images
        )

        yield dist, remaining_files

    @borrowdoc(DistributionTracer)
    def _get_packagefields_for_files(self, files):
        return

    @borrowdoc(DistributionTracer)
    def _create_package(self, **package_fields):
        return