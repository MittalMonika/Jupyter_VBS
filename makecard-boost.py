import yaml
import os
import gzip
import pickle
import argparse
import dctools
import numpy as np
from typing import Any, IO


class config_input:
    def __init__(self, cfg):
        self._cfg = cfg 
    
    def __getitem__(self, key):
        v = self._cfg[key]
        if isinstance(v, dict):
            return config_input(v)

    def __getattr__(self, k):
        try:
            v = self._cfg[k]
            if isinstance(v, dict):
                return config_input(v)
            return v
        except:
            return None
    def __iter__(self):
        return iter(self._cfg)



class config_loader(yaml.SafeLoader):
    """YAML Loader with `!include` constructor."""
    def __init__(self, stream: IO) -> None:
        """Initialise Loader."""
        try:
            self._root = os.path.split(stream.name)[0]
        except AttributeError:
            self._root = os.path.curdir
        super().__init__(stream)


def construct_include(loader: config_loader, node: yaml.Node) -> Any:
    """Include file referenced at node."""
    filename = os.path.abspath(os.path.join(loader._root, loader.construct_scalar(node)))
    extension = os.path.splitext(filename)[1].lstrip('.')

    with open(filename, 'r') as f:
        if extension in ('yaml', 'yml'):
            return yaml.load(f, config_loader)
        elif extension in ('json', ):
            return json.load(f)
        else:
            return ''.join(f.readlines())

yaml.add_constructor('!include', construct_include, config_loader)


def main():
    parser = argparse.ArgumentParser(description='The Creator of Combinators')
    parser.add_argument("-i"  , "--input"   , type=str, default="./config/input_UL_2018_VBS_boost.yaml")
    parser.add_argument("-v"  , "--variable", type=str, default="nnscore")
    parser.add_argument("-y"  , "--era"     , type=str, default='2018')
    parser.add_argument("-c"  , "--channel" , nargs='+', type=str)
    parser.add_argument("-s"  , "--signal"  , nargs='+', type=str)
    options = parser.parse_args()
    
    config = None
    with open(options.input) as f:
        try:
            config = config_input(
                yaml.load(f.read(), config_loader)
            )
        except yaml.YAMLError as exc:
            print (exc)

    boosthist = {}
    for fname in config.boosthist:
        if '.gz' in fname:
            with gzip.open(fname, "rb") as f:
                boosthist.update(pickle.load(f))
        else:
            with open(fname, 'rb') as f:
                boosthist.update(pickle.load(f))

    if len(options.channel) == 1:
        options.channel = options.channel[0]
    # make datasets per prcess
    datasets = {}
    nsignals = 0
    signal = ""

    for name in config.groups:
        histograms = dict(
            filter(
                lambda _n: _n[0] in config.groups[name].processes,
                boosthist.items()
            )
        )
        
        p = dctools.datagroup(
            histograms = histograms,
            ptype      = config.groups[name].type,
            observable = options.variable,
            name       = name,
            xsections  = config.xsections,
            channel    = options.channel,
            luminosity = config.luminosity.value
        )

        #p.save()
        datasets[p.name] = p
        if p.ptype == "signal":
            signal = p.name
    
    card_name = options.channel+options.era
    card = dctools.datacard(
        name = signal,
        channel= card_name
    )
    card.shapes_headers()

    data_obs = datasets.get("data").get("nominal")
    card.add_observation(data_obs)

    for n, p in datasets.items():
        if p.ptype=="data":
            continue 

        card.add_nominal(p.name, p.get("nominal"), p.ptype)

        card.add_nuisance(p.name, "{:<21}  lnN".format("CMS_lumi_{}".format(options.era)),config.luminosity.uncer)
        card.add_nuisance(p.name, "{:<21}  lnN".format("CMS_RES_e"),  1.005)
        card.add_nuisance(p.name, "{:<21}  lnN".format("CMS_RES_m"),  1.005) 
        card.add_nuisance(p.name, "{:<21}  lnN".format("UEPS")     ,  1.020)

        card.add_shape_nuisance(p.name, "CMS_RES_e", p.get("ElectronEn" ), symmetrise=False)
        card.add_shape_nuisance(p.name, "CMS_EFF_e", p.get("ElecronSF" ), symmetrise=False)
        card.add_shape_nuisance(p.name, "CMS_RES_m", p.get("MuonEn")    , symmetrise=False)
        card.add_shape_nuisance(p.name, "CMS_EFF_m", p.get("MuonSF")    , symmetrise=False)

        card.add_shape_nuisance(p.name, "CMS_JES_{}".format(options.era), p.get("jesTotal")  , symmetrise=False)
        card.add_shape_nuisance(p.name, "CMS_JER_{}".format(options.era), p.get("jer")       , symmetrise=False)
        card.add_shape_nuisance(p.name, "CMS_BTag_{}".format(options.era), p.get("BTagSF")   , symmetrise=False)
        card.add_shape_nuisance(p.name, "CMS_Trig_{}".format(options.era), p.get("TriggerSF"), symmetrise=False)
     
        card.add_shape_nuisance(p.name, "CMS_PU_{}".format(options.era), p.get("puWeight"  ), symmetrise=False)
       
        #QCD scale, PDF and other theory uncertainty
        if 'DY' not in p.name:
            card.add_qcd_scales(
                    p.name, "CMS_QCDScale{}_{}".format(p.name, options.era), 
                    [p.get("QCDScale0"), p.get("QCDScale1"), p.get("QCDScale2")]
        )
        
        # PDF uncertaintites
        if p.name != "TOP":
            card.add_shape_nuisance(p.name, "PDF", p.get("PDF"), symmetrise=False)

        # EWK uncertainties
        if p.name in ["ZZ"]:
            card.add_shape_nuisance(p.name, "EWKZZ", p.get("EWK"), symmetrise=False)
        if p.name in ["WZ"]:
            card.add_shape_nuisance(p.name, "EWKWZ", p.get("EWK"), symmetrise=False)                          
        # define rates
        if p.name  in ["WW"]:
            if "catEM" in card_name:
                card.add_rate_param("NormWW_" + options.era, "catEM*", p.name)
            elif "SR" in card_name:
                card.add_rate_param("NormWW_" + options.era, card_name+'*', p.name)
        # define rate 3L categoryel 
        elif p.name in ["WZ"]:
            if "cat3L" in card_name:
                card.add_rate_param("NormWZ_" + options.era, "cat3L*", p.name)
            elif "SR" in card_name:
                card.add_rate_param("NormWZ_" + options.era, card_name+'*', p.name)
        # define rate for DY category
        elif p.name in ["DY"]:
            if "DY" in card_name:
                card.add_rate_param("NormDY_" + options.era, "catDY*", p.name)
            elif "SR" in card_name:
                card.add_rate_param("NormDY_" + options.era, card_name+'*', p.name)
        # define rate for TOP category
        elif p.name in ["TOP"]:
            if "TOP" in card_name:
                card.add_rate_param("NormTOP_" + options.era, "catTOP*", p.name)
            elif "SR" in card_name:
                card.add_rate_param("NormTOP_" + options.era, card_name+'*', p.name) 
        card.add_auto_stat()

    # saving the datacard
    card.dump()

if __name__ == "__main__":
    main()