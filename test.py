import torch

import options.options as options
from data import create_dataset
from metric import get_fid, get_mIoU
from metric.inception import InceptionV3
from metric.mIoU_score import DRNSeg
from metric.fid_score import calculate_fid_given_paths
import utils.util as util
from models import CycleGAN, MaskCycleGAN, Pix2Pix, MaskPix2Pix
from models import MobileCycleGAN, MaskMobileCycleGAN, MobilePix2Pix, MaskMobilePix2Pix

import os
import time
import ntpath
import copy
import numpy as np
from thop import profile

def test_cyclegan_fid(model, opt):
    opt.phase = 'test'
    opt.num_threads = 0
    opt.batch_size = 1
    opt.serial_batches = True
    opt.no_flip = True
    opt.load_size = 256
    opt.display_id = -1
    dataset = create_dataset(opt)
    model.model_eval()

    result_dir = os.path.join(opt.checkpoints_dir, opt.name, 'test_results')
    util.mkdirs(result_dir)

    fake_A = {}
    fake_B = {}

    for i, data in enumerate(dataset):
        model.set_input(data)
        with torch.no_grad():
            model.forward()
        visuals = model.get_current_visuals()
        fake_B[data['A_paths'][0]] = visuals['fake_B']
        fake_A[data['B_paths'][0]] = visuals['fake_A']
        util.save_images(visuals, model.image_paths, result_dir, direction=opt.direction,
                         aspect_ratio=opt.aspect_ratio)

    # print('Calculating AtoB FID...', flush=True)
    block_idx = InceptionV3.BLOCK_INDEX_BY_DIM[2048]
    inception_model = InceptionV3([block_idx])
    inception_model.to(model.device)
    inception_model.eval()
    npz = np.load(os.path.join(opt.dataroot, 'real_stat_B.npz'))
    AtoB_fid = get_fid(list(fake_B.values()), inception_model, npz, model.device, opt.batch_size)

    block_idx = InceptionV3.BLOCK_INDEX_BY_DIM[2048]
    inception_model = InceptionV3([block_idx])
    inception_model.to(model.device)
    inception_model.eval()
    npz = np.load(os.path.join(opt.dataroot, 'real_stat_A.npz'))
    BtoA_fid = get_fid(list(fake_A.values()), inception_model, npz, model.device, opt.batch_size)

    return AtoB_fid, BtoA_fid

def test_pix2pix_fid(model, opt):
    opt.phase = 'val' # 根据自己的需要修改
    opt.num_threads = 0
    opt.batch_size = 1
    opt.serial_batches = True
    opt.no_flip = True
    opt.load_size = 256
    opt.display_id = -1
    dataset = create_dataset(opt)
    model.model_eval()

    result_dir = os.path.join(opt.checkpoints_dir, opt.name, 'test_results')
    util.mkdirs(result_dir)

    fake_B = {}
    for i, data in enumerate(dataset):
        model.set_input(data)
        with torch.no_grad():
            model.forward()
        visuals = model.get_current_visuals()
        fake_B[data['A_paths'][0]] = visuals['fake_B']
        util.save_images(visuals, model.image_paths, result_dir, direction=opt.direction,
                         aspect_ratio=opt.aspect_ratio)

    block_idx = InceptionV3.BLOCK_INDEX_BY_DIM[2048]
    inception_model = InceptionV3([block_idx])
    inception_model.to(model.device)
    inception_model.eval()
    # npz = np.load(os.path.join(opt.dataroot, 'real_stat_B.npz'))
    # fid = get_fid(list(fake_B.values()), inception_model, npz, model.device, opt.batch_size)
    # commented by WH at 18:29 of 2021-04-10
    fid = calculate_fid_given_paths((opt.src_pics_path, opt.dst_pics_path), 1, True, 2048)

    return fid

def test_pix2pix_mIoU(model, opt):
    opt.phase = 'val'
    opt.num_threads = 0
    opt.batch_size = 1
    opt.serial_batches = True
    opt.no_flip = True
    opt.load_size = 256
    opt.display_id = -1
    dataset = create_dataset(opt)
    model.model_eval()

    result_dir = os.path.join(opt.checkpoints_dir, opt.name, 'test_results')
    util.mkdirs(result_dir)

    fake_B = {}
    names = []
    for i, data in enumerate(dataset):
        model.set_input(data)

        with torch.no_grad():
            model.forward()

        visuals = model.get_current_visuals()
        fake_B[data['A_paths'][0]] = visuals['fake_B']

        for path in range(len(model.image_paths)):
            short_path = ntpath.basename(model.image_paths[0][0])
            name = os.path.splitext(short_path)[0]
            if name not in names:
                names.append(name)
        util.save_images(visuals, model.image_paths, result_dir, direction=opt.direction,
                         aspect_ratio=opt.aspect_ratio)

    drn_model = DRNSeg('drn_d_105', 19, pretrained=False).to(model.device)
    util.load_network(drn_model, opt.drn_path, verbose=False)
    drn_model.eval()

    mIoU = get_mIoU(list(fake_B.values()), names, drn_model, model.device,
                    table_path=os.path.join(opt.dataroot, 'table.txt'),
                    data_dir=opt.dataroot,
                    batch_size=opt.batch_size,
                    num_workers=opt.num_threads)
    return mIoU

def get_flops_parms(model, opt, name, verbose=False):

    device = torch.device(f'cuda:{opt.gpu_ids[0]}') if len(opt.gpu_ids) > 0 else 'cpu'
    input = torch.randn(1, 3, opt.crop_size, opt.crop_size).to(device)

    macs, params = profile(model, inputs=(input,), verbose=verbose)

    print("%s | Params: %.2fM | MACs: %.2fG" % (name, params / (1000 ** 2), macs / (1000 ** 3)))

test_logs = open('DMAD_1098_2021_04_10_test.log', 'w+')

if __name__ == '__main__':

    start = time.time()
    opt = options.parse()
    opt.isTrain = False

    if opt.load_path is None or not os.path.exists(opt.load_path):
        raise FileExistsError('Load path must be exist!!!')
    device = torch.device(f'cuda:{opt.gpu_ids[0]}') if len(opt.gpu_ids) > 0 else 'cpu'
    ckpt = torch.load(opt.load_path, map_location=device)
    cfg = ckpt['cfg'] if 'cfg' in ckpt.keys() else (None, None)

    # create model
    if opt.model == 'cyclegan':
        if opt.mask:
            model = MaskCycleGAN.MaskCycleGANModel(opt)
        else:
            model = CycleGAN.CycleGANModel(opt, cfg_AtoB=cfg[0], cfg_BtoA=cfg[1])
    elif opt.model == 'pix2pix':
        opt.norm = 'batch'
        opt.dataset_mode = 'aligned'
        opt.pool_size = 0
        if opt.mask:
            model = MaskPix2Pix.MaskPix2PixModel(opt)
        else:
            model = Pix2Pix.Pix2PixModel(opt, filter_cfgs=cfg[0], channel_cfgs=cfg[1])
    elif opt.model == 'mobilecyclegan':
        if opt.mask:
            model = MaskMobileCycleGAN.MaskMobileCycleGANModel(opt)
        else:
            model = MobileCycleGAN.MobileCycleGANModel(opt, cfg_AtoB=cfg[0], cfg_BtoA=cfg[1])
    elif opt.model == 'mobilepix2pix':
        opt.norm = 'batch'
        opt.dataset_mode = 'aligned'
        opt.pool_size = 0
        if opt.mask:
            model = MaskMobilePix2Pix.MaskMobilePix2PixModel(opt)
        else:
            model = MobilePix2Pix.MobilePix2PixModel(opt, cfg=cfg[0])
    else:
        raise NotImplementedError('%s not implemented' % opt.model)

    get_flops_parms(model, opt, opt.model)
    model.load_models(opt.load_path)

    if opt.model == 'cyclegan' or opt.model == 'mobilecyclegan':
        AtoB_fid, BtoA_fid = test_cyclegan_fid(model, copy.copy(opt))
        print('AtoB FID: %.2f' % AtoB_fid)
        print('BtoA FID: %.2f' % BtoA_fid)
    elif opt.model == 'pix2pix' or opt.model == 'mobilepix2pix':
        if 'cityscapes' in opt.dataroot:
            mIoU = test_pix2pix_mIoU(model, copy.copy(opt))
            print('mIoU: %.2f' % mIoU)
        else:
            print('FID calculation starts!')
            print('FID calculating!')
            fid = test_pix2pix_fid(model, copy.copy(opt))
            end = time.time()
            print('FID: %.2f' % fid)
            print('FID: %.2f' % fid, file = test_logs)
            print('Time used: %.2f' % (end - start))
            print('Time used: %.2f' % (end - start), file = test_logs)
            print('FID calculation finished!')
    else:
        raise NotImplementedError('%s not implements!' % opt.model)