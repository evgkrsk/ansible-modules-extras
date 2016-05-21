#!/usr/bin/python
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

DOCUMENTATION = '''
---
module: attr
version_added: "2.2"
short_description: get/set/unset attributes on a Linux file system
description:
     - Manages Linux filesystem attributes, requires I(chattr)/I(lsattr)/I(xargs) utilities.
       Note that usually only superuser or process with system capability can change this attributes.
options:
  path:
    required: false
    default: None
    aliases: ['name']
    description:
      - The full path of the object to get/set/unset attribute.
  attr:
    required: false
    default: None
    description:
      - The attribute to set/unset. One or more letters from "aAcCdDeijsStTu". See chattr(1) for details. Required with C(path)
  state:
    required: false
    default: present
    choices: [ 'present', 'absent' ]
    description:
      - Defines which state you want to do. Only used with C(path)
        C(present) sets C(attr), this is default
        C(absent) clears C(attr)
  recursive:
    required: false
    default: no
    choices: ["yes", "no"]
    description:
      - Get/set attributes recursive. Default is False. Only used with C(path)
  filelist:
    required: false
    default: None
    description:
      - path to JSON dump file to save (when C(path) used) or load (without C(path)) attributes. In later case all other arguments is ignored.

author: "Evgenii Terechkov (@evgkrsk)"
notes:  []
'''

EXAMPLES = '''
# Sets immutable attribute
- attr: path=/etc/foo.conf attr=i

# Recursive remove immutable attribute
- attr: name=/etc/foo.conf attr=i state=absent recursive=yes

# Restore attributes from JSON dump (note that other args is ignored)
- attr: filelist=/path/to/list attr=ia state=absent

# Get current attributes and dump it in JSON
- attr: path=/etc/foo.bar filelist=/path/to/remote/dump.json
'''

RETURN = '''
msg:
  description: human-readable action description or error message
  returned: always
  type: string
  sample: "attributes loaded"
attr:
  description: machine-readable attributes dump
  returned: success
  type: dictionary
  sample: { "/path/to/object": "i" }
'''

VALID_ATTR = "aAcCdDeijsStTu"

def get_attr(module,path,recursive):
    '''
    Return dictionary with object name as key and attributes as value (both is strings)
    '''
    cmd = [ module.get_bin_path('lsattr', required=True) ]
    if recursive: cmd.append('-R')
    else: cmd.append('-d')
    cmd.append(path)

    result = _run_attr(module,cmd)

    if path and os.path.isdir(path) and recursive:
        cmd = [ module.get_bin_path('lsattr', required=True) ]
        cmd.append('-d')
        cmd.append(path)
        result2 =_run_attr(module,cmd)
        result.update(result2)
        return result
    else:
        return result

def _attr(module, path, attr, recursive, oper=None):
    '''
    Format arguments for chattr and run it
    '''
    cmd = [ module.get_bin_path('chattr', required=True) ]
    if recursive: cmd.append('-R')
    if oper == 'add':
        cmd.append('+%s' % attr)
    elif oper == 'rm':
        cmd.append('-%s' % attr)
    elif oper == 'set':
        cmd.append('=%s' % attr)
    cmd.append(path)

    return _run_attr(module,cmd)

def _run_attr(module,cmd):
    '''
    Run command and return attributes as dict (filename=>attribs)
    '''
    try:
        (rc, out, err) = module.run_command(' '.join(cmd), check_rc=True)
    except Exception, e:
        module.fail_json(msg="%s!" % e)

    result = {}
    for line in out.splitlines():
        try:
            dump, dumppath = line.split(None, 1)
        except ValueError:
            continue        # skip non-properly formatted lines
        result[dumppath] = filter(lambda x: x in VALID_ATTR, dump.replace('-',''))
    return result

def main():
    module = AnsibleModule(
        argument_spec = dict(
            path = dict(required=False, aliases=['name'],type='path'),
            attr = dict(required=False),type='str',
            state = dict(required=False, default='present', choices=[ 'present', 'absent' ], type='str'),
            recursive = dict(required=False, type='bool', default=False),
            filelist = dict(required=False,type='path'),
        ),
        supports_check_mode=True,
    )
    path = module.params.get('path')
    attr = module.params.get('attr')
    state = module.params.get('state')
    recursive = module.params.get('recursive')
    filelist = module.params.get('filelist')

    if not path and not filelist:
        module.fail_json(msg="Use either path/name or filelist")

    changed=False
    msg = ""
    res = {}

    if path and attr:                    # set/unset attribute for path/list
        # See chattr(1) for valid attributes:
        if not re.match('^[%s]+$' % VALID_ATTR,attr):
            module.fail_json(msg="Invalid attributes: %s" % attr)

        if path:
            if state == 'present':
                current=get_attr(module,path,recursive)
                if current and current.has_key(path):
                    for a in attr:
                        if a not in current[path]: changed=True # one or more attributes needs to be set
                    if changed and not module.check_mode:
                        res = _attr(module, path,attr,recursive, 'add')
                else:
                    module.fail_json(msg="Cant get attributes for %s" % path)
                # res=current
                msg="attribute(s) %s set" % attr
            elif state == 'absent':
                current=get_attr(module,path,recursive)
                if current and current.has_key(path):
                    for a in attr:
                        if a in current[path]: changed=True # one or more attributes needs to be set
                    if changed and not module.check_mode:
                        res = _attr(module, path,attr,recursive,'rm')
                else:
                    module.fail_json(msg="Cant get attributes for %s" % path)
                # res=current
                msg="attribute(s) %s removed" % (attr)
    elif filelist and not path: # restore from JSON dump
        with open(filelist, 'r') as f:
            target = json.load(f)
            res = target
        msg="attributes loaded"
        current=get_attr(module, os.path.normpath(os.path.dirname(os.path.commonprefix(target.keys()))),True) # get current state with recursive query for topdir
        need_change={}
        attribs2files={}
        for obj in target:
            obj_t = os.path.normpath(obj) # strip trailing slashes if exists
            if obj_t not in current: continue # skip object if it is not exists (deleted?)
            if target[obj] != current[obj_t]:
                need_change[obj] = target[obj]
                if attribs2files.has_key(target[obj]):
                    attribs2files[target[obj]].append(obj)
                else:
                    attribs2files[target[obj]]=[obj]

        if need_change:
            changed=True
            res=attribs2files
            cmd = module.get_bin_path('xargs', required=True)
            cat = module.get_bin_path('cat', required=True)
            cmd += ' -0 -P 0 chattr' # run chattr processes in parallel
            for attribs in attribs2files:
                command = cmd + " =%s" % attribs
                if not module.check_mode:
                    (rc, out, err) = module.run_command("%s|%s" % (cat,command),check_rc=True,data='\0'.join(attribs2files[attribs]),binary_data=True,use_unsafe_shell=True)
                    if out or err: msg=out+"\n"+err # override output message if stdout/stderr is not-empty
    elif path and not attr:                       # get attribute for path
        res=get_attr(module,path,recursive)
        if filelist:
            # append trailing slash to dirs to speedup loading back
            # (to avoid running lsattr -R ..)
            dump = {}
            for key in res:
                if os.path.isdir(key): dump["%s/" % key]=res[key]
                else: dump[key]=res[key]
            with open(filelist, 'w') as f:
                json.dump(dump, f, indent=1)
            msg="attributes dumped"
    else:
        module.fail_json(msg="Unknown arguments combination")

    module.exit_json(changed=changed, msg=msg, attr=res)

# import module snippets
from ansible.module_utils.basic import *

if __name__ == '__main__':
    main()
