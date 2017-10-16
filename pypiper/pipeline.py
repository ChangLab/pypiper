""" Pipeline base class """

import abc
from collections import Counter, OrderedDict
import sys
if sys.version_info < (3, 3):
    from collections import Iterable, Mapping
else:
    from collections.abc import Iterable, Mapping

from stage import Stage, translate_stage_name


__author__ = "Vince Reuter"
__email__ = "vreuter@virginia.edu"


__all__ = ["Pipeline", "UnknownPipelineStageError"]



class Pipeline(object):
    """
    Generic pipeline framework.

    :param name: Name for the pipeline; arbitrary, just used for messaging.
    :type name: str
    :param manager: The pipeline manager to
    :type manager: pypiper.PipelineManager
    """
    
    __metaclass__ = abc.ABCMeta
    
    
    def __init__(self, name, manager=None):

        super(Pipeline, self).__init__()

        self.name = name
        self.manager = manager

        # Translate stage names; do this here to complicate a hypothetical
        # attempt to override or otherwise redefine the way in which
        # stage names are handled, parsed, and translated.
        self._unordered = _is_unordered(self.stages)
        if self._unordered:
            print("NOTICE: Unordered definition of stages for "
                  "pipeline {}".format(self.name))

        # Get to a sequence of pairs of key (possibly in need of translation)
        # and actual callable. Key is stage name and value is either stage
        # callable or an already-made stage object.
        stages = self.stages.items() \
                if isinstance(self.stages, Mapping) else self.stages
        # Stage spec. parser handles callable validation.
        name_stage_pairs = [_parse_stage_spec(s) for s in stages]

        # Pipeline must have non-empty definition of stages.
        if not stages:
            raise ValueError("Empty stages")

        # Ensure that each pipeline stage is callable, and map names
        # between external specification and internal representation.
        self._internal_to_external = dict()
        self._external_to_internal = dict()
        self._name_stage_pairs = []

        for name, stage in name_stage_pairs:

            # Use external translator to further confound redefinition.
            internal_name = translate_stage_name(name)

            # Check that there's not a checkpoint name collision.
            if internal_name in self._internal_to_external:
                already_mapped = self._internal_to_external[internal_name]
                errmsg = "Duplicate stage name resolution (stage names are too " \
                         "similar.) '{}' and '{}' both resolve to '{}'".\
                    format(name, already_mapped, internal_name)
                raise ValueError(errmsg)

            # Store the stage name translations and the stage itself.
            self._external_to_internal[name] = internal_name
            self._internal_to_external[internal_name] = name
            self._name_stage_pairs.append((internal_name, stage))


    def _seek_start(self, start=None):
        """ Seek to the first stage to run. """
        pass


    @abc.abstractproperty
    def stages(self):
        """
        Define the names of pipeline processing stages.

        :return: Collection of pipeline stage names.
        :rtype: Iterable[str]
        """
        pass


    @property
    def stage_names(self):
        """
        Fetch the pipeline's stage names as specified by the pipeline
        class author (i.e., not necessarily those that are used for the
        checkpoint files)

        :return:
        """
        return list(self._external_to_internal.keys())


    def run(self, start=None, stop=None):
        """
        Run the pipeline, optionally specifying start and/or stop points.

        :param start: Name of stage at which to begin execution.
        :type start: str
        :param stop: Name of stage at which to cease execution.
        :type stop: str
        """

        # TODO: validate starting point against checkpoint flags for
        # TODO (cont.): earlier stages if the pipeline defines its stages as a
        # TODO (cont.): sequence (i.e., probably prohibit start point with
        # TODO (cont): nonexistent earlier checkpoint flag(s).)

        # Ensure that a stage name--if specified--is supported.
        for s in [start, stop]:
            if s is None or s in self.stage_names:
                continue
            raise UnknownPipelineStageError(s, self)

        # Permit order-agnostic pipelines, but warn.
        if self._unordered and (start or stop):
            print("WARNING: Starting and stopping points are nonsense for "
                  "pipeline with unordered stages.")

        # TODO: consider context manager based on start/stop points.

        for name, stage in self._name_stage_pairs:
            # TODO: check against start point name and for checkpoints.
            pass


    @staticmethod
    def _exec_stage(func, *args, **kwargs):
        func(*args, **kwargs)


    def is_complete(self, stage):
        """
        Determine whether the pipeline's completed the stage indicated.
        
        :param stage: Name of stage to check for completion status.
        :type stage: str
        :return: Whether this pipeline's completed the indicated stage.
        :rtype: bool
        :raises UnknownStageException: If the stage name given is undefined 
            for the pipeline, a ValueError arises.
        """
        if stage not in self.stages:
            raise UnknownPipelineStageError(stage, self)



class UnknownPipelineStageError(Exception):
    """
    Triggered by use of unknown/undefined name for a pipeline stage.
    
    :param stage_name: Name of the stage triggering the exception.
    :type stage_name: str
    :param pipeline: Pipeline for which the stage is unknown/undefined.
    :type pipeline: Pipeline
    """
    
    def __init__(self, stage_name, pipeline=None):
        message = stage_name
        if pipeline is not None:
            try:
                stages = pipeline.stages
            except AttributeError:
                # Just don't contextualize the error with known stages.
                pass
            else:
                message = "{}; defined stages: {}".\
                        format(message, ", ".join(stages))
        super(UnknownPipelineStageError, self).__init__(message)



def _is_unordered(collection):
    """
    Determine whether a collection appears to be unordered.

    This is a conservative implementation, allowing for the possibility that
    someone's implemented Mapping or Set, for example, and provided an
    __iter__ implementation that defines a consistent ordering of the
    collection's elements.

    :param collection: Object to check as an unordered collection.
    :type collection object
    :return: Whether the given object appears to be unordered
    :rtype: bool
    :raises TypeError: If the given "collection" is non-iterable, it's
        illogical to investigate whether it's ordered.
    """
    if not isinstance(collection, Iterable):
        raise TypeError("Non-iterable alleged collection: {}".
                        format(type(collection)))
    return isinstance(collection, set) or \
           (isinstance(collection, dict) and
            not isinstance(collection, OrderedDict))



def _parse_stage_spec(stage_spec):
    """
    Handle alternate Stage specifications, returning Stage or TypeError.

    Isolate this parsing logic from any iteration. TypeError as single
    exception type funnel also provides a more uniform way for callers to
    handle specification errors (e.g., skip a stage, warn, re-raise, etc.)

    :param stage_spec:
    :type stage_spec: (str, callable) | callable
    :return: Pair of name and Stage instance from parsing input specification
    :rtype: (name, Stage)
    """

    # The logic used here, a message to a user about how to specify Stage.
    req_msg = "Stage specification must be either a {0} itself, a " \
              "(<name>, {0}) pair, or a callable with a __name__ attribute " \
              "(e.g., a function)".format(Stage.__name__)

    # Simplest case is stage itself.
    if isinstance(stage_spec, Stage):
        return stage_spec

    # Handle alternate forms of specification.
    try:
        # Unpack pair of name and stage, requiring name first.
        name, stage = stage_spec
    except ValueError:
        # Attempt to parse stage_spec as a single named callable.
        try:
            name = stage_spec.__name__
        except AttributeError:
            raise TypeError(req_msg)
        stage = stage_spec

    # Ensure that the stage is callable.
    if not hasattr(stage, "__call__"):
        raise TypeError(req_msg)

    return name, Stage(stage, name=name)
