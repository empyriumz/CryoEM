import torch
import argparse
import json
import logging
from pathlib import Path
from timeit import default_timer as timer
from tqdm import tqdm
import mrcfile
from models.map_splitter import reconstruct_maps
from models.unet import UNetRes
from utils.utils import load_data, logging_related, process_config


def inference(conf):
    assert conf.checkpoint.trained_weights is not None
    RANDOM_SEED = int(conf.general.seed)
    torch.manual_seed(RANDOM_SEED)
    torch.cuda.manual_seed(RANDOM_SEED)
    device = (
        torch.device("cuda:{}".format(conf.general.gpu_id))
        if torch.cuda.is_available()
        else "cpu"
    )

    dataloader = load_data(conf, training=False)

    model = UNetRes(n_blocks=conf.model.n_blocks, act_mode=conf.model.act_mode).to(
        device
    )
    logging.info("Load model from {}".format(conf.checkpoint.trained_weights))
    checkpoint = torch.load(conf.checkpoint.trained_weights)
    model.load_state_dict(checkpoint)

    logging.info("Start inference for {} samples".format(len(dataloader)))
    batch_size = conf.training.batch_size
    torch.backends.cudnn.benchmark = True
    model.eval()
    with torch.no_grad():
        for x, original_shape, id in tqdm(dataloader):
            x = x.squeeze()
            y_pred = torch.tensor(())
            for indx in range(0, x.shape[0], batch_size):
                x_partial = x[indx : indx + batch_size].unsqueeze(dim=1).to(device)
                y_pred_partial = model(x_partial)
                y_pred = torch.cat(
                    (y_pred, y_pred_partial.squeeze(dim=1).detach().cpu()),
                    dim=0,
                )

            y_pred_recon = reconstruct_maps(
                y_pred.numpy(),
                original_shape,
                box_size=conf.data.box_size,
                core_size=conf.data.core_size,
            )
            if conf.test_data.save_output:
                with mrcfile.open(
                    conf.test_data.data_path
                    + "/emd_{}/resampled_map_{}.mrc".format(id[0], id[0]),
                    mode="r",
                ) as input_raw_map:
                    meta_data = input_raw_map.header
                with mrcfile.new(
                    conf.output_path + "/pred_{}.mrc".format(id[0])
                ) as mrc:
                    mrc.set_data(y_pred_recon)
                    mrc.header.cella.x = meta_data.cella.x
                    mrc.header.cella.y = meta_data.cella.y
                    mrc.header.cella.z = meta_data.cella.z
                    mrc.header.nxstart = meta_data.nxstart
                    mrc.header.nystart = meta_data.nystart
                    mrc.header.nzstart = meta_data.nzstart


if __name__ == "__main__":
    start = timer()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path of inference configuration file",
    )
    args = parser.parse_args()
    """
    Read configuration and dump the configuration to output dir
    """
    with open(args.config, "r") as f:
        conf = json.load(f)
    with open(conf["checkpoint"]["model_config"], "r") as f:
        model_conf = json.load(f)
    conf = {**conf, **model_conf}
    conf = process_config(conf, config_name=Path(args.config).stem, training=False)

    """
    logging related part
    """
    logging_related(rank=0, output_path=conf.output_path, debug=False, training=False)
    inference(conf)
    end = timer()
    logging.info("Total time used: {:.1f}".format(end - start))
