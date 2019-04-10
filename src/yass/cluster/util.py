import numpy as np
import logging
import os
import tqdm
import parmap

from yass.empty import empty

def make_CONFIG2(CONFIG):
    ''' Makes a copy of several attributes of original config parameters
        to be sent into parmap function; original CONFIG can't be pickled;
    '''
    
    # make a copy of the original CONFIG object;
    # multiprocessing doesn't like the methods in original CONFIG        
    CONFIG2 = empty()
    CONFIG2.recordings=empty()
    CONFIG2.resources=empty()
    CONFIG2.deconvolution=empty()
    CONFIG2.data=empty()
    CONFIG2.cluster=empty()
    CONFIG2.cluster.prior=empty()
    CONFIG2.cluster.min_spikes = CONFIG.cluster.min_spikes

    CONFIG2.recordings.spike_size_ms = CONFIG.recordings.spike_size_ms
    CONFIG2.recordings.sampling_rate = CONFIG.recordings.sampling_rate
    CONFIG2.recordings.n_channels = CONFIG.recordings.n_channels
    
    CONFIG2.resources.n_processors = CONFIG.resources.n_processors
    CONFIG2.resources.multi_processing = CONFIG.resources.multi_processing
    CONFIG2.resources.n_sec_chunk = CONFIG.resources.n_sec_chunk

    CONFIG2.data.root_folder = CONFIG.data.root_folder
    CONFIG2.data.geometry = CONFIG.data.geometry
    CONFIG2.geom = CONFIG.geom
    
    CONFIG2.cluster.prior.a = CONFIG.cluster.prior.a
    CONFIG2.cluster.prior.beta = CONFIG.cluster.prior.beta
    CONFIG2.cluster.prior.lambda0 = CONFIG.cluster.prior.lambda0
    CONFIG2.cluster.prior.nu = CONFIG.cluster.prior.nu
    CONFIG2.cluster.prior.V = CONFIG.cluster.prior.V

    CONFIG2.neigh_channels = CONFIG.neigh_channels
    CONFIG2.cluster.max_n_sec_chunk = CONFIG.cluster.max_n_sec_chunk
    
    CONFIG2.spike_size = CONFIG.spike_size

    return CONFIG2

def partition_input(save_dir, max_time,
                    fname_spike_index, fname_up=None):

    # make directory
    if not os.path.isdir(save_dir):
        os.makedirs(save_dir)

    # load data
    spike_index = np.load(fname_spike_index)
    if fname_up is not None:
        up_data = np.load(fname_up)
        spike_index_up = up_data['spike_train_up']
        templates_up = up_data['templates_up']

    # consider only spikes times less than max_time
    idx_keep = np.where(spike_index[:,0] < max_time)[0]

    # re-organize spike times and templates id
    n_units = np.max(spike_index[:, 1]) + 1
    spike_index_list = [[] for ii in range(n_units)]
    for j in idx_keep:
        tt, ii = spike_index[j]
        spike_index_list[ii].append(tt)

    if fname_up is not None:
        up_id_list = [[] for ii in range(n_units)]
        for j in idx_keep:
            ii = spike_index[j, 1]
            up_id = spike_index_up[j, 1]
            up_id_list[ii].append(up_id)


    # partition upsampled templates also
    # and save them
    fnames = []
    for unit in range(n_units):

        fname = os.path.join(save_dir, 'partition_{}.npz'.format(unit))

        if fname_up is not None:
            unique_up_ids = np.unique(up_id_list[unit])
            up_templates = templates_up[unique_up_ids]
            new_id_map = {iid: ctr for ctr, iid in enumerate(unique_up_ids)}
            up_id2 = [new_id_map[iid] for iid in up_id_list[unit]]

            np.savez(fname,
                     spike_times = spike_index_list[unit],
                     up_ids = up_id2,
                     up_templates = up_templates)
        else:
            np.savez(fname,
                     spike_times = spike_index_list[unit])
       
        fnames.append(fname)
        
    return np.arange(n_units), fnames

def gather_clustering_result(result_dir, out_dir):

    '''load clustering results
    '''

    logger = logging.getLogger(__name__)
    
    logger.info("gathering clustering results")

    # make output folder
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    # convert clusters to templates
    templates = []
    spike_indexes = []
    
    filenames = sorted(os.listdir(result_dir))
    for fname in filenames:
        data = np.load(os.path.join(result_dir, fname))
        temp_temp = data['templates']
        if (temp_temp.shape[0]) != 0:
            templates.append(temp_temp)
            temp = data['spiketime']
            for s in range(len(temp)):
                spike_indexes.append(temp[s])

    spike_indexes = np.array(spike_indexes)    
    templates = np.vstack(templates)

    logger.info("{} units loaded: ".format(len(spike_indexes)))

    fname_templates = os.path.join(out_dir, 'templates.npy')
    np.save(fname_templates, templates)

    # rearange spike indees from id 0..N
    spike_train = np.zeros((0,2), 'int32')
    for k in range(spike_indexes.shape[0]):    
        temp = np.zeros((spike_indexes[k].shape[0],2), 'int32')
        temp[:,0] = spike_indexes[k]
        temp[:,1] = k
        spike_train = np.vstack((spike_train, temp))

    fname_spike_train = os.path.join(out_dir, 'spike_train.npy')
    np.save(fname_spike_train, spike_train)

    return fname_templates, fname_spike_train

def get_normalized_templates(templates, neigh_channels, ref_template):

    """
    plot normalized templates on their main channels and secondary channels
    templates: number of channels x temporal window x number of units
    geometry: number of channels x 2
    """

    K, R, C = templates.shape
    mc = np.argmax(templates.ptp(1), 1)

    # get main channel templates
    templates_mc = np.zeros((K, R))
    for k in range(K):
        templates_mc[k] = templates[k, :, mc[k]]

    # shift templates_mc
    best_shifts_mc = align_get_shifts_with_ref(
                    templates_mc,
                    ref_template)
    templates_mc = shift_chans(templates_mc, best_shifts_mc)
    ptp_mc = templates_mc.ptp(1)

    # normalize templates
    norm_mc = np.linalg.norm(templates_mc, axis=1, keepdims=True)
    templates_mc /= norm_mc

    # get secdonary channel templates
    templates_sec = np.zeros((0, R))
    best_shifts_sec = np.zeros(0)
    unit_ids_sec = np.zeros((0), 'int32')
    for k in range(K):
        neighs = np.copy(neigh_channels[mc[k]])
        neighs[mc[k]] = False
        neighs = np.where(neighs)[0]
        templates_sec = np.concatenate((templates_sec, templates[k, :, neighs]), axis=0)
        best_shifts_sec = np.hstack((best_shifts_sec, np.repeat(best_shifts_mc[k], len(neighs))))
        unit_ids_sec = np.hstack((unit_ids_sec, np.ones(len(neighs), 'int32')*k))

    # shift templates_sec
    best_shifts_sec = align_get_shifts_with_ref(
                    templates_sec,
                    ref_template)
    templates_sec = shift_chans(templates_sec, best_shifts_sec)
    ptp_sec = templates_sec.ptp(1)

    # normalize templates
    norm_sec = np.linalg.norm(templates_sec, axis=1, keepdims=True)
    templates_sec /= norm_sec

    return templates_mc, templates_sec, ptp_mc, ptp_sec, unit_ids_sec

def pca_denoise(data, pca_mean, pca_components):
    data_pca = np.matmul(data-pca_mean, pca_components.T)
    return np.matmul(data_pca, pca_components)+pca_mean
