""" Tests for the Pipeline data type """

from functools import partial
import glob
import os
import pytest
from pypiper import Pipeline, PipelineManager
from pypiper.manager import COMPLETE_FLAG, RUN_FLAG
from pypiper.pipeline import \
        checkpoint_filepath, pipeline_filepath, \
        IllegalPipelineDefinitionError, IllegalPipelineExecutionError, \
        UnknownPipelineStageError
from pypiper.stage import Stage
from pypiper.utils import flag_name, translate_stage_name
from helpers import named_param


__author__ = "Vince Reuter"
__email__ = "vreuter@virginia.edu"


# Use a weird suffix for glob specificity.
OUTPUT_SUFFIX = ".testout"
FILE1_NAME = "file1{}".format(OUTPUT_SUFFIX)
FILE2_NAME = "file2{}".format(OUTPUT_SUFFIX)
FILE3_NAME = "file3{}".format(OUTPUT_SUFFIX)
FILENAMES = [FILE1_NAME, FILE2_NAME, FILE3_NAME]

FILE1_TEXT = "hello there"
FILE2_TEXT = "hello2"
FILE3_TEXT = "third"
CONTENTS = [FILE1_TEXT, FILE2_TEXT, FILE3_TEXT]

FILE_TEXT_PAIRS = list(zip(FILENAMES, CONTENTS))
TEST_PIPE_NAME = "test-pipe"


def pytest_generate_tests(metafunc):
    if "test_type" in metafunc.fixturenames and \
            metafunc.cls == MostBasicPipelineTests:
        metafunc.parametrize(
                argnames="test_type", 
                argvalues=["effects", "stage_labels", 
                           "checkpoints", "pipe_flag"])


@pytest.fixture
def pl_mgr(request, tmpdir):
    """ Provide a PipelineManager and ensure that it's stopped. """
    pm = PipelineManager(
            name=TEST_PIPE_NAME, outfolder=tmpdir.strpath, multi=True)
    def _ensure_stopped():
        pm.stop_pipeline()
    request.addfinalizer(_ensure_stopped)
    return pm


@pytest.fixture
def dummy_pipe(pl_mgr):
    """ Provide a basic Pipeline instance for a test case. """
    return DummyPipeline(pl_mgr)


def _write_file1(folder):
    _write(*FILE_TEXT_PAIRS[0], folder=folder)


def _write_file2(folder):
    _write(*FILE_TEXT_PAIRS[1], folder=folder)


def _write_file3(folder):
    _write(*FILE_TEXT_PAIRS[2], folder=folder)


BASIC_ACTIONS = [_write_file1, _write_file2, _write_file3]
STAGE_SPECS = ["stage", "name", "function"]


def _write(filename, content, folder=None):
    path = os.path.join(folder, filename)
    with open(path, 'w') as f:
        f.write(content)



@pytest.fixture
def stage(request):
    """
    Provide a test case with a pipeline stage.

    :param pytest.fixtures.FixtureRequest request: Test case in need of the
        parameterization
    :return str | pypiper.Stage | function: The stage provided, in the
        desired format.
    """
    # Ensure that the test case has the needed fixtures.
    stage_fixture_name = "point"
    spec_type_name = "spec_type"
    for fixture_name in [stage_fixture_name, spec_type_name]:
        if fixture_name not in request.fixturenames:
            raise ValueError("No '{}' fixture".format(stage_fixture_name))
    s = request.getfixturevalue(stage_fixture_name)
    spec_type = request.getfixturevalue(spec_type_name)
    return _parse_stage(s, spec_type)



def _parse_stage(stage, spec_type):
    # Determine how point is to be specified.
    if spec_type == "stage":
        stage = Stage(stage)
    elif spec_type == "name":
        stage = Stage(stage).name
    elif spec_type == "function":
        assert hasattr(stage, "__call__")
    else:
        raise ValueError("Unknown specification type: {}".format(spec_type))
    return stage



class DummyPipeline(Pipeline):
    """ Basic pipeline implementation for tests """

    def __init__(self, manager):
        super(DummyPipeline, self).__init__(TEST_PIPE_NAME, manager=manager)

    @property
    def stages(self):
        """
        Establish the stages/phases for this test pipeline.

        :return list[pypiper.Stage]: Sequence of stages for this pipeline.
        """
        # File content writers parameterized with output folder.
        fixed_folder_funcs = []
        for f in [_write_file1, _write_file2, _write_file3]:
            f_fixed = partial(f, folder=self.outfolder)
            f_fixed.__name__ = f.__name__
            fixed_folder_funcs.append(f_fixed)
        return [Stage(f) for f in fixed_folder_funcs]



class EmptyStagesPipeline(Pipeline):
    """ Illegal (via empty stages) Pipeline definition. """

    def __init__(self, manager):
        super(EmptyStagesPipeline, self).__init__(
                TEST_PIPE_NAME, manager=manager)

    @property
    def stages(self):
        return []


class NameCollisionPipeline(Pipeline):
    """ Illegal (via empty stages) Pipeline definition. """

    def __init__(self, manager):
        super(NameCollisionPipeline, self).__init__(
                TEST_PIPE_NAME, manager=manager)

    @property
    def stages(self):
        name = "write file1"
        return [("write file1", _write_file1),
                (translate_stage_name(name), _write_file1)]



class RunPipelineCornerCaseTests:
    """ Tests for exceptional cases of pipeline execution. """


    @named_param(argnames="point", argvalues=BASIC_ACTIONS)
    @named_param(argnames="spec_type", argvalues=STAGE_SPECS)
    @named_param(argnames="inclusive", argvalues=[False, True])
    def test_start_equals_stop(
            self, dummy_pipe, point, spec_type, stage, inclusive):
        """ Start=stop is only permitted if stop should be run. """

        _assert_pipeline_initialization(dummy_pipe)

        # Inclusion determines how to make the call, and the expectation.
        if inclusive:
            # start = inclusive stop --> single stage runs.
            dummy_pipe.run(start=stage, stop_after=stage)
            _assert_checkpoints(dummy_pipe, [stage])
        else:
            # start = exclusive stop --> exception
            with pytest.raises(IllegalPipelineExecutionError):
                dummy_pipe.run(start=stage, stop_at=stage)


    @pytest.mark.parametrize(
            argnames=["start", "stop"],
            argvalues=[(_write_file2, _write_file1),
                       (_write_file3, _write_file2),
                       (_write_file3, _write_file1)])
    @pytest.mark.parametrize(argnames="spec_type", argvalues=STAGE_SPECS)
    @pytest.mark.parametrize(
            argnames="stop_type", argvalues=["stop_at", "stop_after"])
    def test_start_after_stop(
            self, dummy_pipe, start, stop, stop_type, spec_type):
        """ Regardless of specification type, start > stop is prohibited. """
        start = _parse_stage(start, spec_type)
        stop = _parse_stage(stop, spec_type)
        with pytest.raises(IllegalPipelineExecutionError):
            dummy_pipe.run(**{"start": start, stop_type: stop})


    @named_param(
            argnames="undefined_stage",
            argvalues=["unsupported-pipeline-stage", "unknown_phase"])
    @named_param(argnames="stage_point",
                 argvalues=["start", "stop_at", "stop_after"])
    def test_unknown_stage(self, dummy_pipe, undefined_stage, stage_point):
        """ Start specification must be of known stage name. """
        with pytest.raises(UnknownPipelineStageError):
            dummy_pipe.run(**{stage_point: undefined_stage})


    @named_param(argnames="stop_at", argvalues=BASIC_ACTIONS)
    @named_param(argnames="stop_after", argvalues=BASIC_ACTIONS)
    @named_param(argnames="spec_type", argvalues=STAGE_SPECS)
    def test_stop_at_and_stop_after(
            self, dummy_pipe, stop_at, stop_after, spec_type):
        """ Inclusive and exclusive stop cannot both be provided. """
        inclusive_stop = _parse_stage(stop_after, spec_type)
        exclusive_stop = _parse_stage(stop_at, spec_type)
        kwargs = {"stop_at": exclusive_stop, "stop_after": inclusive_stop}
        with pytest.raises(IllegalPipelineExecutionError):
            dummy_pipe.run(**kwargs)


    def test_empty_stages_is_prohibited(self, pl_mgr):
        """ Pipeline must have non-empty stages """
        with pytest.raises(IllegalPipelineDefinitionError):
            EmptyStagesPipeline(manager=pl_mgr)


    def test_stage_name_collision_is_prohibited(self, pl_mgr):
        """ Each stage needs unique translation, used for checkpoint file. """
        with pytest.raises(IllegalPipelineDefinitionError):
            NameCollisionPipeline(manager=pl_mgr)



class MostBasicPipelineTests:
    """ Test pipeline defined with notion of 'absolute minimum' config. """


    def test_runs_through_full(self, dummy_pipe, test_type):
        """ The entire basic pipeline should execute. """

        # Start with clean output folder.
        _assert_pipeline_initialization(dummy_pipe)

        # Make the call under test.
        dummy_pipe.run(start=None, stop_at=None, stop_after=None)
        
        if test_type == "effects":
            # We're interested in existence and content of targets.
            exp_files, _ = zip(*FILE_TEXT_PAIRS)
            _assert_output(dummy_pipe, exp_files)
            fpath_text_pairs = [(pipeline_filepath(dummy_pipe, fname), content)
                                for fname, content in FILE_TEXT_PAIRS]
            for fpath, content in fpath_text_pairs:
                _assert_expected_content(fpath, content)

        elif test_type == "checkpoints":
            # Interest is on checkpoint file existence.
            for stage in dummy_pipe.stages:
                chkpt_fpath = checkpoint_filepath(stage, dummy_pipe)
                try:
                    assert os.path.isfile(chkpt_fpath)
                except AssertionError:
                    print("Stage '{}' file doesn't exist: '{}'".format(
                        stage.name, chkpt_fpath))
                    raise

        elif test_type == "stage_labels":
            # Did the Pipeline correctly track it's execution?
            _assert_stage_states(dummy_pipe, [], dummy_pipe.stages)

        elif test_type == "pipe_flag":
            # The final flag should be correctly set.
            _assert_pipeline_completed(dummy_pipe)

        else:
            raise ValueError("Unknown test type: {}".format(test_type))


    def test_skip_completed(self, dummy_pipe, test_type):
        """ Pre-completed stage(s) are skipped. """

        _assert_pipeline_initialization(dummy_pipe)

        first_stage = dummy_pipe.stages[0]
        first_stage_chkpt_fpath = checkpoint_filepath(first_stage, dummy_pipe)
        open(first_stage_chkpt_fpath, 'w').close()
        assert os.path.isfile(first_stage_chkpt_fpath)

        exp_skips = [first_stage]
        exp_execs = dummy_pipe.stages[1:]

        # This should neither exist nor be created.
        first_stage_outfile = pipeline_filepath(
                dummy_pipe.manager, filename=FILE1_NAME)
        assert not os.path.isfile(first_stage_outfile)
        
        # Do the action.
        dummy_pipe.run()
        
        if test_type == "effects":
            # We should not have generated the first stage's output file.
            # That notion is covered in the outfiles assertion.
            _assert_output(dummy_pipe, FILENAMES[1:])
            assert not os.path.isfile(first_stage_outfile)
            # We should have the correct content in files from stages run.
            for fname, content in FILE_TEXT_PAIRS[1:]:
                fpath = os.path.join(dummy_pipe.outfolder, fname)
                _assert_expected_content(fpath, content)

        elif test_type == "checkpoints":
            # We've manually created the first checkpoint file, and the
            # others should've been created by the run() call.
            _assert_checkpoints(dummy_pipe, exp_stages=dummy_pipe.stages)

        elif test_type == "stage_labels":
            _assert_stage_states(dummy_pipe, exp_skips, exp_execs)

        elif test_type == "pipe_flag":
            _assert_pipeline_completed(dummy_pipe)
        else:
            raise ValueError("Unknown test type: '{}'".format(test_type))


    @named_param(argnames="stop_index", argvalues=range(len(BASIC_ACTIONS) + 1))
    @named_param(argnames="stop_spec_type",
                 argvalues=["stage", "function", "name"])
    def test_start_point(
            self, dummy_pipe, test_type, stop_index, stop_spec_type):
        """ A pipeline may be started from an arbitrary checkpoint. """
        pass


    def test_start_before_completed_checkpoint(self, dummy_pipe, test_type):
        pass


    def test_can_skip_downstream_completed(self, dummy_pipe, test_type):
        pass


    def test_can_rerun_downstream_completed(self, dummy_pipe, test_type):
        pass


    def test_stop_at(self, dummy_pipe, test_type):
        pass


    def test_stop_after(self, dummy_pipe, test_type):
        pass



def _assert_checkpoints(pl, exp_stages):
    """
    Assert equivalence between expected and observed checkpoint files.

    :param pypiper.Pipeline pl: Pipeline for which to validate checkpoints.
    :param Iterable[str | pypiper.Stage] exp_stages: Stage(s) or name(s)
        that are expected to have checkpoint file present.
    """
    exp_fpaths = [checkpoint_filepath(s, pl.manager) for s in exp_stages]
    obs_fpaths = glob.glob(checkpoint_filepath("*", pm=pl.manager))
    assert len(exp_fpaths) == len(obs_fpaths)
    assert set(exp_fpaths) == set(obs_fpaths)



def _assert_expected_content(fpath, content):
    """
    Determine whether a filepath has the expected content.

    :param str fpath: Path to file of interest.
    :param str content: Expected file content.
    :return bool: Whether observation matches expectation.
    """
    assert os.path.isfile(fpath)
    exp_content = content.split(os.linesep)
    with open(fpath, 'r') as f:
        obs_content = [l.rstrip(os.linesep) for l in f.readlines()]
    assert exp_content == obs_content



def _assert_output(pl, expected_filenames):
    """
    Assert equivalence--with respect to presence only--between expected
    collection of output file and the observed output file collection for a
    pipeline.

    :param pypiper.Pipeline pl: pipeline for which output is to be checked
    :param Iterable[str] expected_filenames:
    :return:
    """
    obs_outfiles = glob.glob(pipeline_filepath(
            pl.manager, "*{}".format(OUTPUT_SUFFIX)))
    assert len(expected_filenames) == len(obs_outfiles)
    expected_filepaths = []
    for fname in expected_filenames:
        fpath = fname if os.path.isabs(fname) else \
                pipeline_filepath(pl.manager, filename=fname)
        expected_filepaths.append(fpath)
    assert set(expected_filepaths) == set(obs_outfiles)



def _assert_pipeline_completed(pl):
    """ Assert, based on flag file presence, that a pipeline's completed. """
    flags = glob.glob(pipeline_filepath(pl.manager, filename=flag_name("*")))
    assert 1 == len(flags)
    exp_flag = pipeline_filepath(pl, suffix="_" + flag_name(COMPLETE_FLAG))
    try:
        assert os.path.isfile(exp_flag)
    except AssertionError:
        print("FLAGS: {}".format(flags))
        raise



def _assert_pipeline_initialization(pl):
    """
    Assert that a test case begins with output folder in expected state.

    :param pypiper.Pipeline pl: Pipeline instance for test case.
    """
    # TODO: implement.
    suffices = {"_commands.sh", "_profile.tsv",
                "_{}".format(flag_name(RUN_FLAG))}
    exp_init_contents = \
            [pipeline_filepath(pl.manager, suffix=s) for s in suffices]
    obs_init_contents = [pipeline_filepath(pl.manager, filename=n)
                         for n in os.listdir(pl.outfolder)]
    assert len(exp_init_contents) == len(obs_init_contents)
    assert set(exp_init_contents) == set(obs_init_contents)



def _assert_stage_states(pl, expected_skipped, expected_executed):
    """ Assert equivalence between expected and observed stage states. """
    assert expected_skipped == pl.skipped
    assert expected_executed == pl.executed
