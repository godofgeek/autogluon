import mxnet as mx
from mxnet.util import use_np


@use_np
def average_checkpoints(checkpoint_paths, out_path):
    data_dict_l = []
    avg_param_dict = dict()
    for path in checkpoint_paths:
        data_dict = mx.npx.load(path)
        data_dict_l.append(data_dict)
    for key in data_dict_l[0]:
        arr = None
        for i in range(len(data_dict_l)):
            if arr is None:
                arr = data_dict_l[i][key]
            else:
                arr += data_dict_l[i][key]
        arr /= len(data_dict_l)
        avg_param_dict[key] = arr
    mx.npx.save(out_path, avg_param_dict)
