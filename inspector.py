#!/usr/bin/env python
# encoding: utf-8

import requests
from util import *
from formats import *
from math import ceil
from construct import *
from os.path import splitext, join
from azure import WindowsAzureError

from azure.servicemanagement import get_certificate_from_publish_settings
from azure.servicemanagement import ServiceManagementService
from azure import _validate_not_none,ETree
import os
import sys
from azure.storage import BlobService
from config import default_subscription_id

PTR_TYPE = {
        0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0,
        8: 0, 9: 0, 10: 0, 11: 0, 12: 1, 13: 2, 14: 3,
        }
#(options, args) = get_options()
options = type('my_option', (object,), {})()
global cache
cache = {}
last_query_files_num = 0

#@log_time
def get_superblock(ph):
    """TODO: Docstring for get_superblock.

    :partition: TODO
    :returns: TODO

    """
    return Superblock.parse(get_blob_page(ph, 1024, 1024, blob_service=options.blob_service,
              container=options.container, vhd=options.vhd))


#@log_time
def get_group_desc_table(ph, block_size, gts):
    """TODO: Docstring for get_group_desc_table.

    :returns: TODO

    """
    offset = ceil(2048.0 / block_size) * block_size
    Group_desc_table = OptionalGreedyRange(Group_desc)

    return Group_desc_table.parse(get_blob_page(ph, offset, block_size*gts, blob_service=options.blob_service,
              container=options.container, vhd=options.vhd))


#@log_time
def get_blob_by_key(ph, offset, page_size,
                  blob_service, container, vhd):
    """TODO: Docstring for get_blob_page.

    :offset: TODO
    :page_size: TODO
    :returns: TODO

    """
    rangerange = 'bytes=%d-%d' % (ph+offset, ph+offset+page_size-1)
    
    if (container, vhd, rangerange) in cache :
        return cache[(container, vhd, rangerange)]
    else :
        cache[(container, vhd, rangerange)] = blob_service.get_blob(container, vhd, x_ms_range=rangerange)
        return cache[(container, vhd, rangerange)]
    #return blob_service.get_blob(container, vhd, x_ms_range=rangerange)

#@log_time
def check_vhd_type(sas, blob_service, container, vhd):
    """TODO: Docstring for check_vhd_type.

    :properties: TODO
    :returns: TODO

    """
    if blob_service:
        properties = blob_service.get_blob_properties(container, vhd)
    else:
        r = requests.head(sas, headers={
                'x-ms-version': '2014-02-01',
                'Connection': 'Keep-Alive'
                })
        if not r.ok:
            print '\033[91m Download failure. Status code: %d\033[0m' \
                    % (r.status_code)
            exit(0)
        properties = r.headers

    blob_page = get_blob_page(0, int(properties['content-length'])-512, 512, blob_service=options.blob_service,
              container=options.container, vhd=options.vhd)

    return Hd_ftr.parse(blob_page).type


#@log_time
def get_data_ptr(ph, block_size, ptr, ptr_type):
    """TODO: Docstring for get_data_indir1.

    :indir_ptr: TODO
    :returns: TODO

    """
    offset = block_ptr_to_byte(ptr, block_size)
    try:
        blob_page = get_blob_page(ph, offset, block_size, blob_service=options.blob_service,
              container=options.container, vhd=options.vhd)
    except WindowsAzureError, e:
        print e
        return ''

    if ptr_type == 0:
        return blob_page

    Indir_ptr_list = Struct('indir_ptr_list',
                            Array(block_size/4, ULInt32('indir_ptr')))
    parsed = Indir_ptr_list.parse(blob_page)

    data = ''.join((get_data_ptr(ph, block_size, ptr, ptr_type-1)
                    for ptr in parsed.indir_ptr_list))

    return data


#@log_time
def get_data_extent(ph, extent, block_size):
    """TODO: Docstring for get_data_extent.

    :extent: TODO
    :returns: TODO

    """
    block_ptr = (extent.start_hi << 32) + extent.start_lo
    offset = block_ptr_to_byte(block_ptr, block_size)

    return get_blob_page(ph, offset, extent.len*block_size, blob_service=options.blob_service,
              container=options.container, vhd=options.vhd)


#@log_time
def get_data_idx(ph, idx, block_size):
    """TODO: Docstring for get_data_idx.

    :idx: TODO
    :returns: TODO

    """
    block_ptr = (idx.leaf_hi << 32) + idx.leaf_lo
    offset = block_ptr_to_byte(block_ptr, block_size)
    Node_block = Struct('index_node_block', Ext4_extent_header,
                        Array(block_size/12-1, Ext4_extent))

    return Node_block.parse(get_blob_page(ph, offset, block_size, blob_service=options.blob_service,
              container=options.container, vhd=options.vhd))


#@log_time
def get_data_ext4_tree(ph, extent_tree, block_size):
    """TODO: Docstring for get_data_from_ext4_i_block.

    :extent_tree: TODO
    :returns: TODO

    """
    if extent_tree.ext4_extent_header.depth == 0:
        tmp = sorted(((extent.block, get_data_extent(ph, extent, block_size))
                      for index, extent in enumerate(extent_tree.ext4_extent)
                      if index < extent_tree.ext4_extent_header.entries),
                     key=lambda e: e[0])
    else:
        Indexs = Array(extent_tree.ext4_extent_header.max, Ext4_extent_idx)
        indexs = Indexs.parse(Ext4_extents.build(extent_tree.ext4_extent))
        tmp = sorted(((idx.block,
                       get_data_ext4_tree(ph, get_data_idx(ph, idx,
                                                           block_size),
                                          block_size))
                      for index, idx in enumerate(indexs)
                      if index < extent_tree.ext4_extent_header.entries),
                     key=lambda e: e[0])

    return reduce(lambda a, b: (0, ''.join([a[1], b[1]])), tmp, (0, ''))[1]


#@log_time
def download_ext3_file(ph, inode, filename, block_size, vhd, path):
    """TODO: Docstring for download_ext3_file.

    :inode: TODO
    :returns: TODO

    """
    data = ''.join((get_data_ptr(ph, block_size, ptr, PTR_TYPE[index])
                    for index, ptr in enumerate(inode.blocks_ptr) if ptr))

    with open(''.join(['./', vhd, join(path, filename)]), 'w') as result:
        result.write(data)

    return True


#@log_time
def download_ext4_file(ph, inode, filename, block_size, vhd, path):
    """TODO: Docstring for download_ext4_file.

    :returns: TODO

    """
    data = get_data_ext4_tree(ph, inode.ext4_extent_tree,
                              block_size)[:inode.size]

    with open(''.join(['./', vhd, join(path, filename)]), 'w') as result:
        result.write(data)

    return True


#@log_time
def block_ptr_to_byte(block_ptr, block_size):
    """TODO: Docstring for block_ptr_to_byte.

    :block_ptr: TODO
    :returns: TODO

    """
    return block_size * block_ptr


#@log_time
def parse_KB(superblock):
    """TODO: Docstring for parse_KB.

    :superblock: TODO
    :returns: TODO

    """
    KB_INT = {
            'OneKB': 1024,
            'TwoKB': 2048,
            'FourKB': 4096,
            }

    return KB_INT[superblock.log_block_size]


# If filetype feature flag is turn off, the ext4_dir_entry instead of
# ext4_dir_entry2 will be used, but it doesn't matter to us.
#@log_time
def search_i(ph, inode, index, block_size, to_inode,
             path_list, filename, extension):
    """TODO: Docstring for search_i.

    :returns: TODO

    """
    if inode.flags.EXTENTS:
        data = get_data_ext4_tree(ph, inode.ext4_extent_tree, block_size)
    else:
        data = ''.join((get_data_ptr(ph, block_size, ptr, PTR_TYPE[index])
                        for index, ptr in enumerate(inode.blocks_ptr) if ptr))

    directory = Dirs2.parse(data)
    if index == len(path_list):
        return [(item.inode, item.name) for item in directory
                if filename and item.name == filename
                or extension and splitext(item.name)[1] == extension
                or filename == '' and extension == '']
    else:
        inodes = [search_i(ph, to_inode(item.inode),
                           index+1, block_size, to_inode, options.path_list, options.filename, options.extension)
                  for item in directory if item.name == path_list[index]]
        if inodes:
            return inodes[0]
        else:
            print '\033[91m The directory isn\'t exist.\033[0m'
            return []


#@log_time
def parse_partition(partition):
    """TODO: Docstring for parse_partition.

    :partition: TODO
    :returns: TODO

    """
    ph = partition.starting_sector * 512
    superblock = get_superblock(ph)
    block_size = parse_KB(superblock)
    inodes_per_group = superblock.inodes_per_group
    # group descriptors table size
    gts = ceil((superblock.inodes_count/inodes_per_group)/(block_size/32.0))
    group_desc_table = get_group_desc_table(ph, block_size, gts)
    inode_type = {
            128: {4: Ext4_inode_128, 3: Ext3_inode_128, },
            256: {4: Ext4_inode_256, 3: Ext3_inode_256, },
            }
    inode_tables = {}

    Inode = inode_type[superblock.inode_size][4]
    Inode_table = Struct('inode_table', Array(inodes_per_group, Inode))
    its = inodes_per_group * superblock.inode_size  # inode table size.

    #@log_time
    def to_inode(num):
        """TODO: Docstring for to_inode.

        :num: TODO
        :group_desc_table: TODO
        :returns: TODO

        """
        block_group = (num-1) / inodes_per_group
        local_index = (num-1) % inodes_per_group

        if block_group not in inode_tables:
            group_desc = group_desc_table[block_group]
            offset = block_ptr_to_byte(group_desc.inode_table_ptr, block_size)
            inode_tables[block_group] = Inode_table.parse(
                    get_blob_page(ph, offset, its, blob_service=options.blob_service,
              container=options.container, vhd=options.vhd))

        inode_table = inode_tables[block_group]
        inode = inode_table.inode[local_index]
        if not inode.flags.EXTENTS:
            inode = Ext3_inode_128.parse(Inode.build(inode))

        return inode

    root = to_inode(2)
    target = [(inode_num, name) for inode_num, name
              in search_i(ph, root, 0, block_size, to_inode, options.path_list, options.filename, options.extension)]
    
    global last_query_files_num
    last_query_files_num = len(target)
    if options.ls:
        for inode, name in target:
            print name
        print 'Total: %d files' % (len(target))
        return True

    target = [(to_inode(inode_num), name) for inode_num, name in target]
    len1 = len([download_ext4_file(ph, inode, name, block_size, options.vhd, options.path)
                for inode, name in target
                if inode.flags.EXTENTS and not inode.mode.IFDIR])
    len2 = len([download_ext3_file(ph, inode, name, block_size, vhd=options.vhd, path=options.path)
                for inode, name in target
                if not inode.flags.EXTENTS and not inode.mode.IFDIR])
    print '%d ext4 files + %d ext2/3 files have been downloaded.' % (len1, len2)

    return True


# TODO(shiehinms): Complete the dictionary.
#@log_time
def part_type(pt):
    """TODO: Docstring for part_type.

    :pt: TODO
    :returns: TODO

    """
    partition_type = {
            0x00: 'Empty',
            0x82: 'Linux swap space',
            }

    return partition_type.setdefault(pt, 'Non-Linux')


#@log_time
def parse_image():
    """TODO: Docstring for parse_image.

    :returns: TODO

    """
    mbr = Mbr.parse(get_blob_page(0, 0, 512, blob_service=options.blob_service,
              container=options.container, vhd=options.vhd))

    for partition in mbr.mbr_partition_entry:
        pt = partition.partition_type
        if pt == 0x83 or pt == 0x93:
            partition.boot_indicator == 0x80 and parse_partition(partition)
        else:
            print '\033[93m Unsupported partition type \
                    status : %s .\033[0m' % (part_type(pt))

    return True

def get_options2(url, account_key, path, filename, extension, type, ls):
    options.url = url
    options.account_key = account_key
    options.path = path
    options.filename = filename
    options.extension = extension
    options.type = 4
    options.ls = ls
    
    options.extension and options.filename and exit(print_warning())
    
    tmp = urlparse(options.url)
    options.account_name = tmp.netloc.split('.')[0]
    options.container = tmp.path.split('/')[1]
    options.vhd = tmp.path.split('/')[2]
    options.host_base = tmp.netloc[tmp.netloc.find('.'):]

    if options.account_key:
        options.blob_service = BlobService(options.account_name,
                                           options.account_key,
                                           host_base=options.host_base)
    else:
        options.blob_service = None

    options.path_list = split_path(options.path)

#@log_time
def old_main(url="", account_key="", path="", filename="", extension="", type=4, ls=False):
    """TODO: Docstring for main.
    :returns: TODO

    """
    get_options2(url, account_key, path, filename, extension, type, ls)
    if options.path[0] != '/':
        print '\033[91m Support only absolute path.\033[0m'
        exit(0)

    HD_TYPE_FIXED = 2
    HD_TYPE_DYNAMIC = 3

    init_dir(''.join(['./', options.vhd, options.path]))
    check_vhd_type(sas=options.url, blob_service=options.blob_service,
              container=options.container, vhd=options.vhd) == HD_TYPE_FIXED and parse_image() or \
            check_vhd_type(sas=options.url, blob_service=options.blob_service,
              container=options.container, vhd=options.vhd) == HD_TYPE_DYNAMIC and True

def inspect():
    config = __import__('config')
    if config.default_subscription_name == "" :
        print "Please select an account"
        exit
    subscription_id = config.default_subscription_id
    cert_file = "pem\\" + config.default_subscription_name + '.pem'
    _validate_not_none('cert_file',cert_file)
    sms = ServiceManagementService(subscription_id, cert_file)
    
    url = sys.argv[2]
    storage_name = url[8:url.find('.')]
    storage_account_key = sms.get_storage_account_keys(storage_name).storage_service_keys.primary.encode('ascii','ignore')
    
    nowpath = "/"
    
    def get_sentence(s) :
        st = s.find(' ')
        while st < len(s) and s[st] ==  ' ' :
            st += 1
        ed = len(s)
        for i in range(st, len(s)) :
            if s[i] == ' ' and s[i-1] != '\\' :
                ed = i
                break
        while ed>0 and s[ed-1] == '/' :
            ed -= 1
        return s[st:ed].replace("//", "/")
    
    global last_query_files_num
    while True :
        cmd = raw_input(nowpath+" $ ")
        if cmd.split(' ')[0] == "quit" :
            break
        elif cmd.split(' ')[0] == "ls" :
            old_main(url=url, account_key=storage_account_key, path=nowpath, ls=True)
        elif cmd.startswith("cd ") :
            sentence = get_sentence(cmd)
            if sentence != "" :
                if sentence == ".." :
                    if nowpath != "/" :
                        nowpath = nowpath[:nowpath[:-1].rfind('/')+1]
                elif sentence[0] == '/' :
                    old_main(url=url, account_key=storage_account_key, path=sentence, ls=True)
                    if last_query_files_num == 0 :
                        print "no such directory"
                    else :
                        nowpath = sentence + "/"
                elif sentence != "" :
                    old_main(url=url, account_key=storage_account_key, path=(nowpath+sentence), ls=True)
                    if last_query_files_num == 0 :
                        print "no such directory"
                    else :
                        nowpath += sentence + "/"
        elif cmd.startswith("download ") :
            sentence = get_sentence(cmd)
            tmp = sentence.rfind('/')
            if sentence != "" :
                old_main(url=url, account_key=storage_account_key, path=(nowpath+sentence[:tmp]), filename=sentence[(tmp+1):])
        else :
            print "invalid command"

def get_help():
    """
    """
    print "command:\n"
    print "python inspector.py inspect <vhd-url>\n"
    print "                    get-account\n"
    print "                    get-default-account\n"
    print "                    select-account <subscription-name>\n"
    print "                    add-account <publishsettings-path>\n"
    print "                    delete-account <subscription-name>\n"
    print "adding account existed will cover old account\n"
    
def main():
    '''
        new version simulate a simple bash
    '''
    
    if len(sys.argv) < 2 :
        get_help()
        return
    if sys.argv[1] == 'inspect' :
        if len(sys.argv) < 3 :
            get_help()
            return
        inspect()
        
    elif sys.argv[1] == 'get-account' :
        config = __import__('config')
        print "    Subscription_name                   Subscription_id"
        print "=========================    ======================================"
        for i in config.accounts:
            print i.rjust(25),config.accounts[i].rjust(40)
        
    elif sys.argv[1] == 'get-default-account' :
        config = __import__('config')
        print 'default_subscription_name: ' + str(config.default_subscription_name) + '\n'
        print 'default_subscription_id: ' + str(config.default_subscription_id) + '\n'
        
    elif sys.argv[1] == 'select-account' :
        if len(sys.argv) < 3 :
            get_help()
            return
        config = __import__('config')
        subscription_name = sys.argv[2]
        for i in range(3,len(sys.argv)) :
            subscription_name += ' '+sys.argv[i]
        if not (subscription_name in config.accounts) :
            print "Account not exist."
            return
        else :
            accounts = config.accounts
            subscription_id = accounts[subscription_name]
            f = open('config.py','w')
            f.write('default_subscription_name=\''+subscription_name+'\'\n')
            f.write('default_subscription_id=\''+subscription_id+'\'\n')
            f.write('accounts='+str(accounts))
            f.close()
            
    elif sys.argv[1] == 'add-account' :
        if len(sys.argv) < 3 :
            get_help()
            return
        publish_settings_path = sys.argv[2]
        for i in range(3,len(sys.argv)) :
            publish_settings_path += ' '+sys.argv[i]
        _validate_not_none('publish_settings_path', publish_settings_path)
        
        # parse the publishsettings file and find the ManagementCertificate Entry
        tree = ETree.parse(publish_settings_path)
        subscriptions = tree.getroot().findall("./PublishProfile/Subscription")
        subscription = subscriptions[0]
        subscription_name = subscription.get('Name')

        subscription_id = get_certificate_from_publish_settings(
            publish_settings_path=publish_settings_path,
            path_to_write_certificate='pem\\' + subscription_name+'.pem',
        )
    
        config = __import__('config')
        accounts = config.accounts
        accounts[subscription_name] = subscription_id
        if config.default_subscription_name == "" :
            tmp = "default_subscription_name=\"" + subscription_name + "\"\n"
            tmp += "default_subscription_id=\"" + subscription_id + "\"\n"
        else :
            f = open('config.py','r')
            tmp = f.readline() + f.readline()
        f = open('config.py','w')
        f.write(tmp)
        f.write('accounts='+str(accounts))
        f.close()
        
    elif sys.argv[1] == 'delete-account' :
        if len(sys.argv) < 3 :
            get_help()
            return
        config = __import__('config')
        accounts = config.accounts
        subscription_name = sys.argv[2]
        for i in range(3,len(sys.argv)) :
            subscription_name += ' '+sys.argv[i]
        accounts.pop(subscription_name, None)
        
        if subscription_name == config.default_subscription_name :
            subscription_name = ''
            subscription_id = ''
        else :
            subscription_name = config.default_subscription_name
            subscription_id = config.default_subscription_id
            
        f = open('config.py','w')
        f.write('default_subscription_name=\"'+subscription_name+'\"\n')
        f.write('default_subscription_id=\"'+subscription_id+'\"\n')
        f.write('accounts='+str(accounts))
        f.close()
    else :
        get_help()
if __name__ == '__main__':
    get_blob_page = get_blob_by_key
    main()
