# Copyright (C) 2017 Network Device Education Foundation, Inc. ("NetDEF")
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

from base import *

class FRRouting(Container):
    def __init__(self, name, host_dir, guest_dir='/root/config', image='bgperf/frr'):
        super(FRR, self).__init__(name, image, host_dir, guest_dir)

    @classmethod
    def build_image(cls, force=False, tag='bgperf/frr', checkout='HEAD', nocache=False):
        cls.dockerfile = '''
FROM ubuntu:16.04
WORKDIR /root
# create users and groups for least-privilege support
RUN groupadd -g 92 frr
RUN groupadd -r -g 85 frrvty
RUN adduser --system --ingroup frr --home /var/run/frr/ \
   --gecos "FRR suite" --shell /sbin/nologin frr
RUN usermod -a -G frrvty frr
# install dependenciens
RUN apt-get update && apt-get install -y \
    git autoconf automake libtool make gawk libreadline-dev \
    texinfo dejagnu pkg-config libpam0g-dev libjson-c-dev bison flex \
    python-pytest libc-ares-dev python3-dev libsystemd-dev

RUN git clone https://github.com/FRRouting/frr.git frr
# build, including examples and documentation to disable '--disable-doc'
RUN cd frr && git checkout {0} && ./bootstrap.sh && \
./configure \
    --prefix=/usr \
    --enable-exampledir=/usr/share/doc/frr/examples/ \
    --localstatedir=/var/run/frr \
    --sbindir=/usr/lib/frr \
    --sysconfdir=/etc/frr \
    --enable-pimd \
    --enable-watchfrr \
    --enable-ospfclient=yes \
    --enable-ospfapi=yes \
    --enable-multipath=64 \
    --enable-user=frr \
    --enable-group=frr \
    --enable-vty-group=frrvty \
    --enable-configfile-mask=0640 \
    --enable-logfile-mask=0640 \
    --enable-rtadv \
    --enable-tcp-zebra \
    --enable-fpm
    --enable-vtysh \
    --with-pkg-git-version \
    --with-pkg-extra-version=-bgperf_frr
RUN cd frr && make -j2 && make check && make install
# is this still necessary?
RUN ldconfig
'''.format(checkout)
        super(FRRouting, cls).build_image(force, tag, nocache)


class FRRoutingTarget(FRRouting, Target):

    CONTAINER_NAME = 'bgperf_FRRouting_target'
    CONFIG_FILE_NAME = 'bgpd.conf'


    def write_config(self, conf, name='bgpd.conf'):
        config = """hostname bgpd
password zebra
router bgp {0}
bgp router-id {1}
""".format(conf['target']['as'], conf['target']['router-id'])

        def gen_neighbor_config(n):
            local_addr = n['local-address'].split('/')[0]
            c = """neighbor {0} remote-as {1}
neighbor {0} advertisement-interval 1
neighbor {0} route-server-client
neighbor {0} timers 30 90
""".format(local_addr, n['as']) # adjust BGP hold-timers if desired
            if 'filter' in n:
                for p in (n['filter']['in'] if 'in' in n['filter'] else []):
                    c += 'neighbor {0} route-map {1} export\n'.format(local_addr, p)
            return c

        with open('{0}/{1}'.format(self.host_dir, name), 'w') as f:
            f.write(config)
            for n in conf['tester']['peers'].values() + [conf['monitor']]:
                f.write(gen_neighbor_config(n))

            if 'policy' in conf:
                seq = 10
                for k, v in conf['policy'].iteritems():
                    match_info = []
                    for i, match in enumerate(v['match']):
                        n = '{0}_match_{1}'.format(k, i)
                        if match['type'] == 'prefix':
                            f.write(''.join('ip prefix-list {0} deny {1}\n'.format(n, p) for p in match['value']))
                            f.write('ip prefix-list {0} permit any\n'.format(n))
                        elif match['type'] == 'as-path':
                            f.write(''.join('ip as-path access-list {0} deny _{1}_\n'.format(n, p) for p in match['value']))
                            f.write('ip as-path access-list {0} permit .*\n'.format(n))
                        elif match['type'] == 'community':
                            f.write(''.join('ip community-list standard {0} permit {1}\n'.format(n, p) for p in match['value']))
                            f.write('ip community-list standard {0} permit\n'.format(n))
                        elif match['type'] == 'ext-community':
                            f.write(''.join('ip extcommunity-list standard {0} permit {1} {2}\n'.format(n, *p.split(':', 1)) for p in match['value']))
                            f.write('ip extcommunity-list standard {0} permit\n'.format(n))

                        match_info.append((match['type'], n))

                    f.write('route-map {0} permit {1}\n'.format(k, seq))
                    for info in match_info:
                        if info[0] == 'prefix':
                            f.write('match ip address prefix-list {0}\n'.format(info[1]))
                        elif info[0] == 'as-path':
                            f.write('match as-path {0}\n'.format(info[1]))
                        elif info[0] == 'community':
                            f.write('match community {0}\n'.format(info[1]))
                        elif info[0] == 'ext-community':
                            f.write('match extcommunity {0}\n'.format(info[1]))

                    seq += 10

        self.config_name = name

    def run(self, conf, brname='', cpus=''):
        ctn = super(FRR, self).run(brname, cpus=cpus)

        if self.config_name == None:
            self.write_config(conf)

        startup = '''#!/bin/bash
ulimit -n 65536
ip a add {0} dev eth1
bgpd -f {1}/{2}
'''.format(conf['target']['local-address'], self.guest_dir, self.config_name)
        filename = '{0}/start.sh'.format(self.host_dir)
        with open(filename, 'w') as f:
            f.write(startup)
        os.chmod(filename, 0777)
        i = dckr.exec_create(container=self.name, cmd='{0}/start.sh'.format(self.guest_dir))
        dckr.exec_inspect(i['Id'])
        dckr.exec_start(i['Id'], detach=True)
        return ctn
