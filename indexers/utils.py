import os
import hashlib
import json
import time
from elasticsearch import Elasticsearch
from elasticsearch_dsl import Index
import ssl
import fcntl
from dotenv import load_dotenv

import pandas as pd

##忽视证书
context = ssl._create_unverified_context()    ##adding new congfig for es

# Ignore warnings
import warnings
from elasticsearch import ElasticsearchWarning
warnings.simplefilter('ignore', ElasticsearchWarning)


load_dotenv() ###本地环境配置


def read_json_file(file):
    read_path = file
    with open(read_path, "r", errors='ignore') as read_file:
        data = json.load(read_file)
    return data


def gen_id_from_url(url, max_length=140):
    if type(url) in (list, tuple):
        if len(url) != 1:
            raise ValueError(f'one url must be provided {url}')
        url = url[0]
    id_ = url.replace('/', '_')

    if len(id_) > max_length:
        id_ = hashlib.md5(id_.encode('utf-8')).hexdigest()

    return id_


def create_es_client() -> Elasticsearch:
    """ Create an Elasticsearch client based on the IP addresses/hostname.
    Returns:
        es: an elasticsearch client.

    """
    elasticsearch_host = os.environ.get('ELASTICSEARCH_HOST')
    
    #elasticsearch_host = 'http://elasticsearch:9201'
    if elasticsearch_host is None:
        raise ValueError('$ELASTICSEARCH_HOST is not defined.')

    elasticsearch_username = os.environ.get('ELASTICSEARCH_USERNAME')
    elasticsearch_password = os.environ.get('ELASTICSEARCH_PASSWORD')



    if elasticsearch_username and elasticsearch_password:
        http_auth = [elasticsearch_username, elasticsearch_password]
    else:
        http_auth = None

    es = Elasticsearch(
        hosts=[elasticsearch_host],
        http_auth=http_auth,
        tim_out=30,
        scheme="https",    ##new config
        ssl_context=context    ##new config
        )

    # Try to reconnect to Elasticsearch for 10 times when failing
    # This is useful when Elasticsearch service is not fully online,
    # which usually happens when starting all services at once.
    for i in range(50):
        if not es.ping():
            time.sleep(1)
            print('[Elasticsearch] waiting for server')
            continue
        else:
            break
    if not es.ping():
        raise ValueError('[Elasticsearch] could not connect to server')
    print(f'[Elasticsearch] connected change to {elasticsearch_host}')
    return es


class ElasticsearchIndexer:

    def __init__(self, index_name):
        self.es = create_es_client()
        self.index_name = index_name
        self.index = self.initialize_index(self.index_name)

    @staticmethod
    def _apply_index_settings(index):
        index.settings(
            index={'mapping': {'ignore_malformed': True}}
            )

    def initialize_index(self, index_name):
        index = Index(index_name, self.es)
        if not index.exists():
            self._apply_index_settings(index)
            index.create()
        return index

    #check if one type of data source has been indexed into es
    def is_in_index(self, field_name, value) -> bool:
        """ Check if the index contains an entry with <field_name> = <value>

        :param field_name: name of the field to check
        :param value: value to match
        :return: True if an entry is found, False otherwise
        """
        query = {
            "query": {
                "bool": {
                    "must": [{
                        "match_phrase": {
                            field_name: value,
                            }
                        }]
                    }
                },
            "from": 0,
            "size": 1
            }
        response = self.es.search(
            index=self.index_name,
            body=query,
            )
        num_hits = response['hits']['total']['value']
        return num_hits > 0

    def ingest_record(self, record_id: str, record: dict):
        """ Index record into elasticsearch

        :param record: record to index
        :param record_id: id of the index entry
        """
        self.es.index(
            index=self.index_name,
            id=record_id,
            body=record,
            )

    def refresh_index(self):
        self.index.refresh()


def get_data_dir():
    data_dir = os.getenv('DATA_DIR')
    if data_dir is None:
        raise ValueError('$DATA_DIR is not defined.')
    return data_dir


def lock_file(file, mode):
    """锁定文件"""
    if mode == 'r':  # 读锁
        fcntl.flock(file, fcntl.LOCK_SH)
    elif mode == 'w':  # 写锁
        fcntl.flock(file, fcntl.LOCK_EX)

def unlock_file(file):
    """解锁文件"""
    fcntl.flock(file, fcntl.LOCK_UN)


def read_csv_with_lock(file_path):
    with open(file_path, 'r') as file:
        lock_file(file, 'r')  # 加读锁
        df = pd.read_csv(file)
        unlock_file(file)  # 解锁
    return df
