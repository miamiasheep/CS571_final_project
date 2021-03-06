#!/usr/bin/env python
import sys
import os
import re
import shutil
import StringIO
import simplejson
import gzip
import tempfile
from optparse import OptionParser
from normalize_pdb import normalize_pdb
from itertools import combinations,product

from utils import *

def parse_args():
    """setup program options parsing"""
    parser = OptionParser(description="""aggregates lists or graphs generated by other programs
and outputs the JSON dict with classifier classes
""")
    parser.add_option("-o", "--output-json", dest="output_json",
                  help="save dictionary to JSON file", metavar="FILE")
    parser.add_option("-i", "--input-json", dest="input_json",
                  help="search doublets dictionary from file", metavar="FILE")
    parser.add_option("--input-dir", dest="input_dir",
                  help="search doublets dictionary from directory", metavar="DIR")
    parser.add_option("--merge", dest="merge",
                  help="merge following groups", metavar="PDB_IDS")
    parser.add_option("--merge-skip-groups", dest="merge_skip_groups",
                  help="skip groups matching the regexp", metavar="REGEXP")
    parser.add_option("--descriptions-dict", dest="descriptions_dict", metavar="JSON_FILE",
                  default="descriptions-dict.json", help="load descriptions dictionary from JSON file")
    parser.add_option("--pdb-id", dest="pdb_id", metavar="ID")
    parser.add_option("--close-doublets-graph", dest="close_doublets_graph", metavar="FILE")
    parser.add_option("--rnaview-graph", dest="rnaview_graph", metavar="FILE")
    parser.add_option("--mc-annotate-graph", dest="mc_annotate_graph", metavar="FILE")
    parser.add_option("--moderna-graph", dest="moderna_graph", metavar="FILE")
    parser.add_option("--fr3d-graph", dest="fr3d_graph", metavar="FILE")
    parser.add_option("--expert-dir", dest="expert_dir", metavar="DIR", default="expert")
    (options, args)  = parser.parse_args()

    if options.pdb_id is None:
        if options.input_json:
            options.pdb_id = os.path.basename(options.input)[0:4].upper()

    return (parser, options, args)

def simplify_desc(prg, desc):
    if prg=='MC':
        desc = re.sub(r"_\d+$","",desc)
    return desc

def cat_list(d):
    n_types_py = ['C','U']
    n_types_pu = ['A','G']
    prg_list = ('RV','MC','MO','FR')
    n_type = d['n_type'].upper()

    n_list = ['all',n_type]
    if n_type[0] in n_types_py and n_type[1] in n_types_py:
        n_list.append('Py-Py')
    elif n_type[0] in n_types_pu and n_type[1] in n_types_pu:
        n_list.append('Pu-Pu')
    elif n_type[0] in n_types_pu and n_type[1] in n_types_py:
        n_list.append('Pu-Py')

    r = []
    r.append("all/all/")
    recognized = 0
    for prg in prg_list:
        if d.has_key('desc_'+prg):
            r.append('recognized/'+prg+'/')
            recognized += 1
    if recognized>0:
        r.append('recognized/all/')
    else:
        r.append('unclassified/all/')
    result = []
    for (pr,suf) in product(r, n_list):
        result.append(pr+suf)
    for suf in n_list:
        for prg1,prg2 in product(prg_list, prg_list):
            if prg1==prg2:
                k = prg1
            else:
                k = prg1 + "_vs_" + prg2
            group_id = 'descriptions/' + k + '/' + suf + '/' + simplify_desc(prg1, d.get('desc_'+prg1,'unrecognized'))
            if prg1!=prg2:
                if not d.has_key('desc_'+prg1):
                    continue
                group_id += '/' + simplify_desc(prg2,d.get('desc_'+prg2,'unrecognized'))
            result.append(group_id)
    return result

def reverse_rv(desc):
    return desc[0:2][::-1]+"_"+desc[3:]

def classifier_cat_list_simple(d, sub_category):
    result = []
    keys = []
    n_type = d['n_type'].upper()
    rev_n_type = n_type[::-1]
    
    
    if sub_category=='bp':
        k1,k2,k3 = ('desc_RV','desc_MC','desc_FR')
    elif sub_category=='stacking':
        k1,k2,k3 = ('desc_MC','desc_MO','desc_FR')
    elif sub_category in ['base-phosphate','base-ribose']:
        k1,k2,k3 = ('desc_FR','desc_FR',None)
    
    if d[k1]!='' and d[k1]==d[k2]:
        result.append('classifier/'+sub_category+'/'+d[k1]+'/'+n_type)
        if sub_category!='base-phosphate' and sub_category!='base-ribose' and (n_type!=rev_n_type or d[k1]!=DoubletDescTool.reverse_desc(d[k1])):
            result.append('!classifier/'+sub_category+'/'+DoubletDescTool.reverse_desc(d[k1])+'/'+rev_n_type)
    elif k3 is not None and d[k2]!='' and d[k2]==d[k3]:
        result.append('classifier/'+sub_category+'/'+d[k3]+'/'+n_type)
        if sub_category!='base-phosphate' and sub_category!='base-ribose' and (n_type!=rev_n_type or d[k3]!=DoubletDescTool.reverse_desc(d[k3])):
            result.append('!classifier/'+sub_category+'/'+DoubletDescTool.reverse_desc(d[k3])+'/'+rev_n_type)
    elif k3 is not None and d[k1]!='' and d[k1]==d[k3]:
        result.append('classifier/'+sub_category+'/'+d[k3]+'/'+n_type)
        if sub_category!='base-phosphate' and sub_category!='base-ribose' and (n_type!=rev_n_type or d[k3]!=DoubletDescTool.reverse_desc(d[k3])):
            result.append('!classifier/'+sub_category+'/'+DoubletDescTool.reverse_desc(d[k3])+'/'+rev_n_type)
    else:
        for k in set([k1,k2,k3]):
            if k is not None and d[k]!='':
                result.append('fuzzy/'+sub_category+'/'+d[k]+'/'+n_type)
                if sub_category!='base-phosphate' and sub_category!='base-ribose' and (n_type!=rev_n_type or d[k]!=DoubletDescTool.reverse_desc(d[k])):
                    result.append('!fuzzy/'+sub_category+'/'+DoubletDescTool.reverse_desc(d[k])+'/'+rev_n_type)
    return result

def classifier_cat_list(d, desc_tool):
    result = []
    n_type = d['n_type'].upper()
    
    (category, sub_category, desc) = desc_tool.interpret_other_results(d)
    print "classifier", d, category, sub_category
    if category=='valid':
        result.append('classifier/'+sub_category+'/'+desc+'/'+n_type)
        if sub_category=='bp':
            if desc[0]!=desc[1] or n_type[0]!=n_type[1]:
                result.append('!classifier/bp/'+reverse_rv(desc)+'/'+n_type[::-1])
    else:
        # we could generate groups diff-MC-RV, only-MC, only-RV
        pass
    return result

def show_results_stats(res):
    for k in sorted(res.keys(), key=lambda x: len(res[x]), reverse=True):
        print " - %s: %d" % (k,len(res[k]))

def reverse_doublet_id(_id):
    tmp = _id.split(":")
    if len(tmp)==2:
        return tmp[1]+":"+tmp[0]
    else:
        return tmp[0]+":"+tmp[2]+":"+tmp[1]

def handle_doublets_dict(options):
    """TODO: remove this method!"""
    desc_tool = DoubletDescTool(load_json(options.descriptions_dict))
    print "loading %s" % options.input_json
    close_doublets = load_json(options.input_json)
    res = {}
    for id,d in close_doublets.items():
        rev_id = reverse_doublet_id(id)
        for c in cat_list(d)+classifier_cat_list(d, desc_tool):
            if c[0]=='!':
                reverse = True
                c = c[1:]
            else:
                reverse = False
            if not res.has_key(c):
                res[c]=[]
            if reverse:
                res[c].append(rev_id)
            else:
                res[c].append(id)
    show_results_stats(res)
    save_json(options.output_json, res)

def handle_doublets_graphs(options):
    pdb_id = options.pdb_id.upper()
    expert = {}
    if options.expert_dir:
        for f in find_files_in_dir(options.expert_dir):
            if re.match(r'^.*json(.gz)?$',f):
                category = os.path.dirname(f).split("/")[-1]
                assert category in ['ref','not-ref','fuzzy','not-fuzzy','unclassified']
                ff = os.path.basename(f).split(".")[0].split("_")
                if len(ff)>=4:
                    sc,n_type,desc1,desc2 = ff[0],ff[1],ff[2],ff[3]
                    desc = desc1+"_"+desc2
                elif len(ff)==3:
                    sc,n_type,desc = ff[0],ff[1],ff[2]
                else:
                    raise Exception("Unknown filename format: %s" % os.path.basename(f))
                assert sc in ['bp','stacking','other','other2','other3']
                assert re.match('^[ACGU]{2}$',n_type)
                
                if not expert.has_key(category):
                    expert[category] = []
                for d_id in load_json(f):
                    if d_id.split(":")[0]==pdb_id:
                        expert[category].append((d_id,sc,n_type,desc))
                        if category in ['bp','stacking']:
                            expert[category].append((
                                DoubletDescTool.reverse_d_id(d_id),
                                sc,
                                DoubletDescTool.reverse_n_type(n_type),
                                DoubletDescTool.reverse_desc(desc)
                            ))

    desc_tool = DoubletDescTool(load_json(options.descriptions_dict))

    close_doublets = GraphTool(options.close_doublets_graph,'dist')
    graphs = {}
    for prg,fn in ('RV',options.rnaview_graph),('MC',options.mc_annotate_graph),('MO',options.moderna_graph),('FR',options.fr3d_graph):
        if fn:
            graphs[prg] = GraphTool(fn)
        else:
            graphs[prg] = GraphTool()

    res = {}
    for short_id in close_doublets.get_ids():
        full_id = options.pdb_id.upper() + ":" + short_id
        rev_full_id = reverse_doublet_id(full_id)
        d = close_doublets.get_contact_by_id(short_id,data=True)
        d_full = d.copy()
        d_bp = d.copy()
        d_st = d.copy()
        d_bph = d.copy()
        d_br = d.copy()
        for prg in ('RV','MC','MO','FR'):
            if graphs[prg]:
                dd = graphs[prg].get_contact_by_id(short_id,data=True)
                if dd.get('desc','')!='':
                    d['desc_%s'%prg] = dd['desc']
                    d_full['desc_%s'%prg] = dd['full_desc']
                if prg in ['RV','MC','FR']:
                    d_bp['desc_%s'%prg] = graphs[prg].get_contact_by_id(short_id,cat='bp',data=False)
                if prg in ['MC','MO','FR']:
                    d_st['desc_%s'%prg] = graphs[prg].get_contact_by_id(short_id,cat='stacking',data=False)
                if prg in ['FR']:
                    d_bph['desc_%s'%prg] = graphs[prg].get_contact_by_id(short_id,cat='base-phosphate',data=False)
                    d_br['desc_%s'%prg] = graphs[prg].get_contact_by_id(short_id,cat='base-ribose',data=False)
        print short_id, d_bp
        categories = []
        if d.get('reverse',False)==False:
            categories += cat_list(d_full)
            categories += classifier_cat_list_simple(d_bp, "bp")
            categories += classifier_cat_list_simple(d_st, "stacking")
        categories += classifier_cat_list_simple(d_bph, "base-phosphate")
        categories += classifier_cat_list_simple(d_br, "base-ribose")
        for c in categories:
            if c[0]=='!':
                reverse = True
                c = c[1:]
            else:
                reverse = False
            if not res.has_key(c):
                res[c]=[]
            if reverse:
                res[c].append(rev_full_id)
            else:
                res[c].append(full_id)
    
    for d_id,sc,n_type,desc in expert.get('not-ref',[]):
        k = 'classifier/'+sc+'/'+desc+'/'+n_type
        x = res.get(k,[])
        if d_id in x:
            print "EXPERT(not-ref): removing %s from %s" % (d_id,k)
            x.remove(d_id)
    for k_prefix,e_key in (('classifier','ref'),('fuzzy','fuzzy')):
        for d_id,sc,n_type,desc in expert.get(e_key,[]):
            k = k_prefix+'/'+sc+'/'+desc+'/'+n_type
            if not res.has_key(k):
                res[k] = []
            x = res.get(k)
            if d_id not in x:
                print "EXPERT(%s): adding %s to %s" % (e_key,d_id,k)
                x.append(d_id)
    # print sorted([x for x in res.keys() if re.match('^class',x)])
    
    # load close-doublets
    # load recognized by RV,MC,MO,FR
    
    #for id,d in close_doublets.items():
    #    for c in cat_list(d)+classifier_cat_list(d, desc_tool):

    show_results_stats(res)
    save_json(options.output_json, res)

def handle_merge(options):
    res = {}
    
    regexp = None
    if options.merge_skip_groups:
        regexp = re.compile(options.merge_skip_groups)
    
    for pdb in options.merge.split(","):
        fn = PDBObject.pdb_fn(pdb,"groups")
        print "loading %s" % fn
        sys.stdout.flush()
        r = load_json(fn)
        for k,v in r.items():
            if regexp and regexp.match(k):
                print " - skipping group %s" % k
                continue
            if not res.has_key(k):
                res[k]=[]
            res[k] += v
        # add by-pdb keys
        for desc in ['all/all',
                     'recognized/all','recognized/RV','recognized/MC','recognized/MO','recognized/FR',
                     'unclassified/all']:
            r_key = desc + "/all"
            res_key = 'by-pdb/'+pdb.upper()+'/'+desc+"/all"
            if regexp and regexp.match(res_key):
                print " - skipping group %s" % res_key
                continue
            if r.has_key(r_key):
                res[res_key]=r[r_key]
    save_json(options.output_json, res)

def main():
    (parser, options, args) = parse_args()
    if options.merge:
        handle_merge(options)
    elif options.close_doublets_graph:
        handle_doublets_graphs(options)
    else:
        if not options.input_json:
            print "select input json"
            parser.print_help()
            exit(1)
        if not options.output_json:
            print "select output"
            parser.print_help()
            exit(1)
        handle_doublets_dict(options)

if __name__ == '__main__':
    main()

