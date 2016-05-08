#!/usr/bin/env python3
#
#########################################################################
#  Copyright 2016 René Frieß                        rene.friess@gmail.com
#  Version 1.1.3
#########################################################################
#  Free for non-commercial use
#
#  Plugin for the software SmartHome.py (NG), which allows to control and read 
#  enigma2 compatible devices such as the VUSolo4k. For the API, the openwebif
#  needs to be installed.
#
#  SmartHomeNG is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  SmartHome.py is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with SmartHome.py (NG). If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################

import datetime
import logging
import socket
import time
import threading
from xml.dom import minidom
import requests
from requests.packages import urllib3
from requests.auth import HTTPDigestAuth

class Enigma2Device():
    """
    This class encapsulates information related to a specific Enigma2Device, such has host, port, ssl, username, password, or related items
    """
    def __init__(self, host, port, ssl, username, password, identifier):
        self.logger = logging.getLogger(__name__)
        self._host = host
        self._port = port
        self._ssl = ssl
        self._username = username
        self._password = password
        self._identifier = identifier
        self._items = []
        self._items_fast = []

    def get_identifier(self):
        """
        Returns the internal identifier of the Enigma2Device

        :return: identifier of the device, as set in plugin.conf
        """
        return self._identifier

    def get_host(self):
        """
        Returns the hostname / IP of the Enigma2Device

        :return: hostname of the device, as set in plugin.conf
        """
        return self._host

    def get_port(self):
        """
        Returns the port of the Enigma2Device

        :return: port of the device, as set in plugin.conf
        """
        return self._port

    def get_items(self):
        """
        Returns added items

        :return: array of items hold by the device
        """
        return self._items

    def get_fast_items(self):
        """
        Returns added items

        :return: array of items hold by the device
        """
        return self._items_fast

    def get_item_count(self):
        """
        Returns number of added items

        :return: number of items hold by the device
        """
        return (len(self._items)+len(self._items_fast))

    def is_ssl(self):
        """
        Returns information if SSL is enabled

        :return: is ssl enabled, as set in plugin.conf
        """
        return self._ssl

    def get_user(self):
        """
        Returns the user for the Enigma2Device

        :return: user, as set in plugin.conf
        """
        return self._username

    def get_password(self):
        """
        Returns the password for the Enigma2Device

        :return: password, as set in plugin.conf
        """
        return self._password

class Enigma2():
    """
    Main class of the Plugin. Does all plugin specific stuff and provides the update functions for the Enigma2Device
    """

    _url_suffix_map = dict([('about','/web/about'),
                            ('deviceinfo', '/web/deviceinfo'),
                            ('epgservice', '/web/epgservice'),
                            ('getaudiotracks', '/web/getaudiotracks'),
                            ('getcurrent', '/web/getcurrent'),
                            ('message', '/web/message'),
                            ('messageanswer','/web/messageanswer'),
                            ('powerstate', '/web/powerstate'),
                            ('remotecontrol', '/web/remotecontrol'),
                            ('subservices', '/web/subservices'),
                            ('zap', '/web/zap')])

    _keys_fast_refresh = ['current_eventtitle','current_eventdescription','current_eventdescriptionextended',
                          'current_volume', 'e2servicename','e2videoheight','e2videowidth','e2apid','e2vpid',
                          'e2instandby']
    _key_event_information = ['current_eventtitle','current_eventdescription','current_eventdescriptionextended']

    def __init__(self, smarthome, username='', password='', host='dreambox', port='80', ssl='True', verify='False', cycle=300, fast_cycle=10, device_id='enigma2'):
        """
        Initalizes the plugin. The parameters describe for this method are pulled from the entry in plugin.conf.

        :param username:           Login name of user, cptional for devices which only support passwords
        :param password:           Password for the Enigma2Device
        :param host:               IP or host name of Enigma2Device
        :param port:               Port of the Enigma2Device (https: 49443, http: 49000)
        :param ssl:                True or False => https or http in URLs
        :param verify:             True or False => verification of SSL certificate
        :param cycle:              Update cycle in seconds
        :param device_id:          Internal identifier of the Enigma2Device
        """
        self.logger = logging.getLogger(__name__)
        self.logger.info('Init Enigma2 Plugin with device_id %s' % device_id)

        self._session = requests.Session()
        self._timeout = 10

        if verify == 'False':
            self._verify = False
        else:
            self._verify = True

        if ssl == 'True':
            ssl = True
            if not self._verify:
                urllib3.disable_warnings()
        else:
            ssl = False

        self._enigma2_device = Enigma2Device(host, port, ssl, username, password, device_id)

        self._cycle = int(cycle)
        self._fast_cycle = int(fast_cycle)
        self._sh = smarthome

        # Response Cache: Dictionary for storing the result of requests which is used for several different items, refreshed each update cycle. Please use distinct keys!
        self._response_cache = dict()

    def run(self):
        """
        Run method for the plugin
        """
        self._sh.scheduler.add(__name__ + "_" + self._enigma2_device.get_identifier(), self._update_loop, cycle=self._cycle)
        self._sh.scheduler.add(__name__ + "_" + self._enigma2_device.get_identifier() + "_fast", self._update_loop_fast, cycle=self._fast_cycle)
        self.alive = True

    def stop(self):
        """
        Stop method for the plugin
        """
        self.alive = False


    def _build_url(self, suffix, parameter=''):
        """
        Builds a request url

        :param suffix: url suffix, e.g. "/upnp/control/x_tam"
        :return: string of the url, dependent on settings of the Enigma2Device
        """
        if self._enigma2_device.is_ssl():
            url_prefix = "https"
        else:
            url_prefix = "http"
        url = "%s://%s:%s%s?%s" % (url_prefix, self._enigma2_device.get_host(), self._enigma2_device.get_port(), suffix, parameter)
        return url

    def _update_loop(self):
        """
        Starts the update loop for all known items.
        """
        self.logger.debug('Starting update loop for identifier %s' % self._enigma2_device.get_identifier())
        for item in self._enigma2_device.get_items():
            if not self.alive:
                return
            self._update(item)

        #empty response cache
        self._response_cache = dict()

    def _update_loop_fast(self, cache=True):
        """
        Starts the fast update loop for all known items.
        """
        self.logger.debug('Starting update loop for identifier %s' % self._enigma2_device.get_identifier())
        for item in self._enigma2_device.get_fast_items():
            if not self.alive:
                return
            if 'enigma2_page' in item.conf:
                self._update(item)
            elif item.conf['enigma2_data_type'] in self._key_event_information:
                self._update_event_items(cache)
            elif item.conf['enigma2_data_type'] == 'current_volume':
                self._update_volume(item, cache)

        # empty response cache
        self._response_cache = dict()

    def parse_item(self, item):
        """
        Default plugin parse_item method. Is called when the plugin is initialized. Selects each item corresponding to
        the Enigma2 device id and adds it to an internal array

        :param item: The item to process.
        """
        if 'device_id' in item.conf:
            value = item.conf['device_id']

            if value == self._enigma2_device.get_identifier():
                # normal items
                if 'enigma2_page' in item.conf:
                    if item.conf['enigma2_page'] in ['about', 'powerstate', 'subservices', 'deviceinfo']:
                        if item.conf['enigma2_data_type'] in self._keys_fast_refresh:
                            self._enigma2_device._items_fast.append(item)
                        else:
                            self._enigma2_device._items.append(item)
                elif 'enigma2_data_type' in item.conf:
                    if item.conf['enigma2_data_type'] in self._keys_fast_refresh:
                        self._enigma2_device._items_fast.append(item)
                    else:
                        self._enigma2_device._items.append(item)
                elif 'enigma2_remote_command_id' in item.conf or 'sref' in item.conf:    # items for TV remote and direct service access
                    return self.execute_item

    def execute_item(self, item, caller=None, source=None, dest=None):
        """
        | Write items values - in case they were changed from somewhere else than the Enigma2 plugin
        | (=the Enigma2Device) to the Enigma2Device.

        :param item: item to be updated towards the Enigma2Device
        """
        if caller != 'Enigma2':
            # enigma2 remote control
            if 'enigma2_remote_command_id' in item.conf:
                self.remote_control_command(item.conf['enigma2_remote_command_id'])
                if item.conf['enigma2_remote_command_id'] in ['105','106','116']: #box was switched to or from standby, auto update
                    self._update_event_items(cache = False)
                    self._update_loop_fast(cache = False)
                elif item.conf['enigma2_remote_command_id'] in ['114','115']: #volume changed, auto update
                    self._update_loop_fast(cache = False)
            elif 'sref' in item.conf:
                self.zap(item.conf['sref'])
                self._update_event_items(cache = False)
                self._update_loop_fast(cache = False)

    def remote_control_command(self, command_id):
        url = self._build_url(self._url_suffix_map['remotecontrol'],
                              'command=%s' % command_id)
        try:
            response = self._session.get(url, timeout=self._timeout,
                                         auth=HTTPDigestAuth(self._enigma2_device.get_user(),
                                                             self._enigma2_device.get_password()), verify=self._verify)
        except Exception as e:
            self.logger.error("Exception when sending GET request: %s" % str(e))
            return

        xml = minidom.parseString(response.content)
        e2result_xml = xml.getElementsByTagName('e2result')
        e2resulttext_xml = xml.getElementsByTagName('e2resulttext')
        if (len(e2resulttext_xml) > 0 and len(e2result_xml) > 0):
            if not e2resulttext_xml[0].firstChild is None and not e2result_xml[0].firstChild is None:
                if e2result_xml[0].firstChild.data == 'True':
                    self.logger.debug(e2resulttext_xml[0].firstChild.data)

    def get_audio_tracks(self):
        """
        Retrieves an array of all available audio tracks
        """
        result = []
        url = self._build_url(self._url_suffix_map['getaudiotracks'])
        try:
            response = self._session.get(url, timeout=self._timeout, auth=HTTPDigestAuth(self._enigma2_device.get_user(),
                                                                                         self._enigma2_device.get_password()),
                                         verify=self._verify)
            xml = minidom.parseString(response.content)
        except Exception as e:
            self.logger.error("Exception when sending GET request: %s" % str(e))
            return

        e2audiotrack_xml = xml.getElementsByTagName('e2audiotrack')
        if (len(e2audiotrack_xml)) > 0:
            for audiotrack_entry_xml in e2audiotrack_xml:
                result_entry = {}
                e2audiotrackdescription_xml = audiotrack_entry_xml.getElementsByTagName('e2audiotrackdescription')

                if (len(e2audiotrackdescription_xml)) > 0:
                    result_entry['e2audiotrackdescription'] = e2audiotrackdescription_xml[0].firstChild.data

                e2audiotrackid_xml = audiotrack_entry_xml.getElementsByTagName('e2audiotrackid')
                if (len(e2audiotrackid_xml)) > 0:
                    result_entry['e2audiotrackid'] = int(e2audiotrackid_xml[0].firstChild.data)

                e2audiotrackpid_xml = audiotrack_entry_xml.getElementsByTagName('e2audiotrackpid')
                if (len(e2audiotrackpid_xml)) > 0:
                    result_entry['e2audiotrackpid'] = int(e2audiotrackpid_xml[0].firstChild.data)

                e2audiotrackactive_xml = audiotrack_entry_xml.getElementsByTagName('e2audiotrackactive')
                if (len(e2audiotrackactive_xml)) > 0:
                    if e2audiotrackactive_xml[0].firstChild.data in 'True':
                        result_entry['e2audiotrackactive'] = True
                    else:
                        result_entry['e2audiotrackactive'] = False

                result.append(result_entry)

        return result

    def zap(self, e2servicereference, title=''):
        """
        Zaps to another service by a given e2servicereference

        :param e2servicereference: reference to the service
        :param title: optional title of "zap" action
        """
        url = self._build_url(self._url_suffix_map['zap'],
                              'sRef=%s&title=%s' % (e2servicereference, title))
        try:
            response = self._session.get(url, timeout=self._timeout,
                                         auth=HTTPDigestAuth(self._enigma2_device.get_user(),
                                                             self._enigma2_device.get_password()), verify=self._verify)
        except Exception as e:
            self.logger.error("Exception when sending GET request: %s" % str(e))
            return

        xml = minidom.parseString(response.content)
        e2state_xml = xml.getElementsByTagName('e2state')
        e2statetext_xml = xml.getElementsByTagName('e2statetext')
        if (len(e2statetext_xml) > 0 and len(e2state_xml) > 0):
            if not e2statetext_xml[0].firstChild is None and not e2state_xml[0].firstChild is None:
                if e2state_xml[0].firstChild.data == 'True':
                    self.logger.debug(e2statetext_xml[0].firstChild.data)

    def send_message(self, messagetext, messagetype=1, timeout=10):
        """
        Sends a message to the Enigma2 Device
        
        messagetext=Text of Message
        messagetype=Number from 0 to 3, 0= Yes/No, 1= Info, 2=Message, 3=Attention
        timeout=Can be empty or the Number of seconds the Message should disappear after.
        """
        url = self._build_url(self._url_suffix_map['message'],'text=%s&type=%s&timeout=%s' % (messagetext, messagetype, timeout))
        try:
            response = self._session.get(url, timeout=self._timeout, auth=HTTPDigestAuth(self._enigma2_device.get_user(),
                                                          self._enigma2_device.get_password()), verify=self._verify)
        except Exception as e:
            self.logger.error("Exception when sending GET request: %s" % str(e))
            return
        
        xml = minidom.parseString(response.content)
        e2result_xml = xml.getElementsByTagName('e2result')
        e2resulttext_xml = xml.getElementsByTagName('e2resulttext')
        if (len(e2resulttext_xml) > 0 and len(e2result_xml) >0):
            if not e2resulttext_xml[0].firstChild is None and not e2result_xml[0].firstChild is None:
                if e2result_xml[0].firstChild.data == 'True':
                    self.logger.debug(e2resulttext_xml[0].firstChild.data)
                    
    def get_answer(self):
        """
        Retrieves the answer to a currently sent message, take care to take the timeout into account in which the answer can be given and start a thread which is polling the answer for that period.
        """
        url = self._build_url(self._url_suffix_map['message'],'getanswer=now')
        try:
            response = self._session.get(url, timeout=self._timeout, auth=HTTPDigestAuth(self._enigma2_device.get_user(),
                                                          self._enigma2_device.get_password()), verify=self._verify)
            xml = minidom.parseString(response.content)
        except Exception as e:
            self.logger.error("Exception when sending GET request: %s" % str(e))
            return

        e2result_xml = xml.getElementsByTagName('e2state')
        e2resulttext_xml = xml.getElementsByTagName('e2statetext')
        if (len(e2resulttext_xml) > 0 and len(e2result_xml) >0):
            if not e2resulttext_xml[0].firstChild is None and not e2result_xml[0].firstChild is None:
                self.logger.debug(e2resulttext_xml[0].firstChild.data)
                if e2result_xml[0].firstChild.data == 'True':                    
                    return e2resulttext_xml[0].firstChild.data

    def _update_event_items(self, cache = True):
        for item in self._enigma2_device.get_fast_items():
            if item.conf['enigma2_data_type'] in ['current_eventtitle', 'current_eventdescription','current_eventdescriptionextended','e2servicename']:
                self._update_current_event(item, cache)

    def _update_volume(self, item, cache = True):
        """
        Retrieves the answer to a currently sent message, take care to take the timeout into account in which the answer can be given and start a thread which is polling the answer for that period.
        """
        url = self._build_url(self._url_suffix_map['getcurrent'])
        self.logger.debug("Getting Volume")
        try:
            response = self._session.get(url, timeout=self._timeout,
                                         auth=HTTPDigestAuth(self._enigma2_device.get_user(),
                                                             self._enigma2_device.get_password()), verify=self._verify)
            xml = minidom.parseString(response.content)
        except Exception as e:
            self.logger.error("Exception when sending GET request: %s" % str(e))
            return

        volume = self._get_value_from_xml_node(xml, 'e2current')
        self.logger.debug("Volume "+volume)
        item(volume)

    def _update_event_items(self, cache=True):
        for item in self._enigma2_device.get_fast_items():
            if item.conf['enigma2_data_type'] in ['current_eventtitle', 'current_eventdescription',
                                                  'current_eventdescriptionextended', 'e2servicename']:
                self._update_current_event(item, cache)

    def _update_current_event(self, item, cache = True):
        """
        Updates information on the current event

        :param item: item to be updated
        """
        url = self._build_url(self._url_suffix_map['subservices'])

        if not 'enigma2_data_type' in item.conf:
            self.logger.error("No enigma2_data_type set in item!")
            return

        self._cached_get_request('subservices', url, cache)

        try:
            xml = minidom.parseString(self._response_cache['subservices'])
        except Exception as e:
            self.logger.error("Exception when parsing response: %s" % str(e))
            return

        element_xml = xml.getElementsByTagName('e2servicereference')
        if (len(element_xml) > 0):
            e2servicereference = element_xml[0].firstChild.data
            #self.logger.debug(e2servicereference)
        else:
            self.logger.error("Attribute %s not available on the Enigma2Device" % item.conf['enigma2_data_type'])

        if not e2servicereference == 'N/A' and not '1:0:0:0:0:0:0:0:0:0' in e2servicereference:
            current_epgservice = self.get_current_epgservice_for_service_reference(e2servicereference)
        else:
            current_epgservice = {}
            current_epgservice['e2eventtitle'] = '-'
            current_epgservice['e2eventdescription'] = '-'
            current_epgservice['e2eventdescriptionextended'] = '-'

        if item.conf['enigma2_data_type'] == 'e2servicename':
            e2servicename = self._get_value_from_xml_node(xml, 'e2servicename')
            if e2servicename is None or e2servicename == 'N/A':
                e2servicename = '-'
            item(e2servicename)
        if item.conf['enigma2_data_type'] == 'current_eventtitle':
            item(current_epgservice['e2eventtitle'])
        elif item.conf['enigma2_data_type'] == 'current_eventdescription':
            item(current_epgservice['e2eventdescription'])
        elif item.conf['enigma2_data_type'] == 'current_eventdescriptionextended':
            item(current_epgservice['e2eventdescriptionextended'])

    def get_current_epgservice_for_service_reference(self, service_reference):
        """
        Retrieves event information for a given service reference id

        :param referece of the service to retrieve data for:
        :return: dict of result data
        """
        url = self._build_url(self._url_suffix_map['epgservice'], 'sRef=%s' % (service_reference))

        try:
            response = self._session.get(url, timeout=self._timeout,
                                         auth=HTTPDigestAuth(self._enigma2_device.get_user(),
                                                             self._enigma2_device.get_password()),
                                         verify=self._verify)
        except Exception as e:
            self.logger.error("Exception when sending GET request: %s" % str(e))
            return

        try:
            xml = minidom.parseString(response.content)
        except Exception as e:
            self.logger.error("Exception when parsing response: %s" % str(e))
            return

        e2event_list_xml = xml.getElementsByTagName('e2event')
        result_entry = {}
        if (len(e2event_list_xml) > 0):
            e2eventdescription = self._get_value_from_xml_node(e2event_list_xml[0], 'e2eventdescription')
            if  e2eventdescription is None:
                e2eventdescription = '-'
            result_entry['e2eventdescription'] = e2eventdescription

            e2eventdescriptionextended = self._get_value_from_xml_node(e2event_list_xml[0], 'e2eventdescriptionextended')
            if e2eventdescriptionextended is None:
                e2eventdescriptionextended = '-'
            result_entry['e2eventdescriptionextended'] = e2eventdescriptionextended

            e2eventtitle = self._get_value_from_xml_node(e2event_list_xml[0], 'e2eventtitle')
            if e2eventtitle is None:
                e2eventtitle = '-'
            result_entry['e2eventtitle'] = e2eventtitle

        return result_entry

    def _update(self, item, cache = True):
        """
        Updates information on diverse items

        :param item: item to be updated
        """

        if not 'enigma2_data_type' in item.conf:
            self.logger.error("No enigma2_data_type set in item!")
            return

        url = self._build_url(self._url_suffix_map[item.conf['enigma2_page']])

        self._cached_get_request(item.conf['enigma2_page'], url, cache)

        try:
            xml = minidom.parseString(self._response_cache[item.conf['enigma2_page']])
        except Exception as e:
            self.logger.error("Exception when parsing response: %s" % str(e))
            return

        element_xml = xml.getElementsByTagName(item.conf['enigma2_data_type'])
        if (len(element_xml) > 0):
            # self.logger.debug(element_xml[0].firstChild.data)
            if item.type() == 'bool':
                if not element_xml[0].firstChild is None:
                    if element_xml[0].firstChild.data == 'true' or element_xml[0].firstChild.data == 'True':
                        item(1)
                    else:
                        item(0)
            elif item.type() == 'num':
                if not element_xml[0].firstChild is None:
                    if (self._represents_int(element_xml[0].firstChild.data)):
                        item(int(element_xml[0].firstChild.data))
                    elif (self._represents_float(element_xml[0].firstChild.data)):
                        item(float(element_xml[0].firstChild.data))
                # todo: evtl alten item wert clearen?
            else:
                if not element_xml[0].firstChild is None:
                    if element_xml[0].firstChild.data == "N/A":
                        item("-")
                    else:
                        item(element_xml[0].firstChild.data)
                else:
                    item("-")
        else:
            self.logger.error("Attribute %s not available on the Enigma2Device" % item.conf['enigma2_data_type'])

    def _cached_get_request(self, cache_key, url, cache=True):
        if not cache_key in self._response_cache or not cache:
            try:
                response = self._session.get(url, timeout=self._timeout,
                                             auth=HTTPDigestAuth(self._enigma2_device.get_user(),
                                                                 self._enigma2_device.get_password()),
                                             verify=self._verify)
            except Exception as e:
                self.logger.error("Exception when sending GET request: %s" % str(e))
                return
            self._response_cache[cache_key] = response.content
        else:
            self.logger.debug("Accessing reponse cache for %s!" % url)

    def _get_value_from_xml_node(self, node, tag_name):
        data = None
        xml = node.getElementsByTagName(tag_name)
        if (len(xml) > 0):
            if not xml[0].firstChild is None:
                data = xml[0].firstChild.data
        return data

    def _represents_int(self, string):
        try:
            int(string)
            return True
        except ValueError:
            return False

    def _represents_float(self, string):
        try:
            float(string)
            return True
        except ValueError:
            return False