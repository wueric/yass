import os
import logging
import datetime
import numpy as np
import os.path

from yass import read_config
from yass.templates.util import (align_templates, merge_templates,
                                 get_templates_parallel)
from yass.templates.clean import clean_up_templates
from yass.util import check_for_files, LoadFile, file_loader


@check_for_files(filenames=[LoadFile('templates.npy'),
                            LoadFile('spike_train.npy')],
                 mode='values', relative_to=None,
                 auto_save=True)
def run(spike_train, tmp_loc, recordings_filename='standardized.bin',
        if_file_exists='skip', save_results=False):
    """Compute templates

    Parameters
    ----------
    spike_train: numpy.ndarray, str or pathlib.Path
        Spike train from cluster step or path to npy file

    tmp_loc: np.array(n_templates)
        At which channel the clustering is done.

    output_directory: str, optional
        Output directory (relative to CONFIG.data.root_folder) used to load
        the recordings to generate templates, defaults to tmp/

    recordings_filename: str, optional
        Recordings filename (relative to CONFIG.data.root_folder/
        output_directory) used to generate the templates, defaults to
        standardized.bin

    if_file_exists: str, optional
      One of 'overwrite', 'abort', 'skip'. Control de behavior for the
      templates.npy. file If 'overwrite' it replaces the files if exists,
      if 'abort' it raises a ValueError exception if exists,
      if 'skip' it skips the operation if the file exists (and returns the
      stored file)

    save_results: bool, optional
        Whether to templates to disk
        (in CONFIG.data.root_folder/relative_to/templates.npy),
        defaults to False

    Returns
    -------
    templates: npy.ndarray
        templates

    spike_train: np.array(n_data, 3)
        The 3 columns represent spike time, unit id,
        weight (from soft assignment)

    groups: list(n_units)
        After template merge, it shows which ones are merged together

    idx_good_templates: np.array
        index of which templates are kept after clean up

    Examples
    --------

    .. literalinclude:: ../../examples/pipeline/templates.py
    """
    spike_train = file_loader(spike_train)

    CONFIG = read_config()

    startTime = datetime.datetime.now()

    Time = {'t': 0, 'c': 0, 'm': 0, 's': 0, 'e': 0}

    logger = logging.getLogger(__name__)

    _b = datetime.datetime.now()

    logger.info("Getting Templates...")

    path_to_recordings = os.path.join(CONFIG.path_to_output_directory,
                                      'preprocess',
                                      recordings_filename)

    # relevant parameters
    merge_threshold = CONFIG.templates.merge_threshold
    spike_size = CONFIG.spike_size
    template_max_shift = CONFIG.templates.max_shift
    neighbors = CONFIG.neigh_channels
    geometry = CONFIG.geom

    # make templates using parallel code
    templates, weights = get_templates_parallel(spike_train,
                                                path_to_recordings,
                                                CONFIG)
   
    # Cat: TODO: Templates probably won't be computed through this 
    #      function any longer; for now disable the remainder of this function
    if False:
        # Cat: this seems to be broken right now, gives error for align_templates
        # logger.info("Getting Templates....")
        # templates, weights = get_templates(spike_train, path_to_recordings,
        #                                   CONFIG.resources.max_memory,
        #                                   2 * (spike_size + template_max_shift))

        # clean up bad templates
        # logger.info("Cleaning Templates...")
        # snr_threshold = 2
        # spread_threshold = 100
        #templates, weights, spike_train, idx_good_templates = clean_up_templates(
            #templates, weights, spike_train, tmp_loc, geometry, neighbors,
            #snr_threshold, spread_threshold)

        logger.info("Aligning Templates...")
        # align templates
        templates, spike_train = align_templates(templates, spike_train,
                                                 template_max_shift)

        logger.info("Merging Templates...")
        # merge templates
        templates, spike_train, groups = merge_templates(
            templates, weights, spike_train, neighbors, template_max_shift,
            merge_threshold)

        # remove the edge since it is bad
        templates = templates[:, template_max_shift:(
            template_max_shift + (4 * spike_size + 1))]

    Time['e'] += (datetime.datetime.now() - _b).total_seconds()

    # report timing
    currentTime = datetime.datetime.now()
    logger.info("Templates done in {0} seconds.".format(
        (currentTime - startTime).seconds))


    templates_dir = os.path.join(CONFIG.path_to_output_directory, 'templates')

    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)

    # Save spike_train_clear_after_templates to be loaded by deconv
    spike_train_clear_after_templates = os.path.join(templates_dir,
                                'spike_train_clear_after_templates.npy')

    np.save(spike_train_clear_after_templates, spike_train)

    # NOTE returning groups and None for test compatibility
    return templates, spike_train, None, None
