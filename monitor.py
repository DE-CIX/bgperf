# Copyright (C) 2016 Nippon Telegraph and Telephone Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from gobgp import GoBGP
import os
from  settings import dckr
import yaml
import json
from threading import Thread

class Monitor(GoBGP):
    def __init__(self, name, host_dir):
        super(Monitor, self).__init__(name, host_dir)

    def run(self, conf, brname=''):
        ctn = super(GoBGP, self).run(brname)
        config = {}
        config['global'] = {
            'config': {
                'as': conf['monitor']['as'],
                'router-id': conf['monitor']['router-id'],
            },
        }
        config ['neighbors'] = [{'config': {'neighbor-address': conf['target']['local-address'].split('/')[0],
                                            'peer-as': conf['target']['as']},
                                 'transport': {'config': {'local-address': conf['monitor']['local-address'].split('/')[0]}},
                                 'timers': {'config': {'connect-retry': 10}}}]
        with open('{0}/{1}'.format(self.host_dir, 'gobgpd.conf'), 'w') as f:
            f.write(yaml.dump(config))
        self.config_name = 'gobgpd.conf'
        startup = '''#!/bin/bash
ulimit -n 65536
ip a add {0} dev eth1
gobgpd -t yaml -f {1}/{2} -l {3} > {1}/gobgpd.log 2>&1
'''.format(conf['monitor']['local-address'], self.guest_dir, self.config_name, 'debug')
        filename = '{0}/start.sh'.format(self.host_dir)
        with open(filename, 'w') as f:
            f.write(startup)
        os.chmod(filename, 0777)
        i = dckr.exec_create(container=self.name, cmd='{0}/start.sh'.format(self.guest_dir))
        dckr.exec_start(i['Id'], detach=True)
        self.config = conf
        return ctn

    def local(self, cmd, stream=False):
        i = dckr.exec_create(container=self.name, cmd=cmd)
        return dckr.exec_start(i['Id'], tty=True, stream=stream)

    def wait_established(self, neighbor):
        it = self.local('gobgp monitor neighbor {0} -j'.format(neighbor), stream=True)
        buf = ''
        for line in it:
            if line == '\n':
                neigh = json.loads(buf)
                if neigh['info']['bgp_state'] == 'BGP_FSM_ESTABLISHED':
                    return
                buf = ''
            else:
                buf += line
