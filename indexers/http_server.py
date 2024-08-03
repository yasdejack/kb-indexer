import csv
import json
import os
from io import StringIO

from flask import Flask, request, jsonify
import subprocess
import threading
import requests

from concurrent.futures import ThreadPoolExecutor

from indexers.utils import lock_file, unlock_file

from flask_sqlalchemy import SQLAlchemy



app = Flask(__name__)




app.config['SQLALCHEMY_DATABASE_URI'] = "mysql+pymysql://root:@mysql:3306/bms"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


db = SQLAlchemy(app)


class RunningTask(db.Model):
    __tablename__ = 'app01_runningtask'
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(255), unique=True, nullable=False)
    contenttype = db.Column(db.String(255), nullable=False)
    org = db.Column(db.String(255), nullable=False)
    repo = db.Column(db.String(255), nullable=True)
    start_time = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(255), nullable=False)


executor = ThreadPoolExecutor(max_workers=1)



def run_process(command, task_id):
    try:
        update_task_status(task_id, 'running')
        process = subprocess.Popen(command, shell=True)
        try:
            process.wait(timeout=3600)  # 超时设置为1小时
        except subprocess.TimeoutExpired:
            process.kill()
            print(f"Task {task_id} timed out and was killed")
    except subprocess.CalledProcessError as e:
        print(f"Task {task_id} failed with error: {e}")
    finally:
        update_task_status(task_id, 'end')


def update_task_status(task_id, status):


    url = 'http://msystem:8001/update_task_status/'
    headers = {'Content-Type': 'application/json'}
    data = {'task_id': task_id, 'status': status}
    response = requests.post(url, headers=headers, data=json.dumps(data))
    if response.status_code == 200:
        print(f"Task {task_id} status updated successfully")
    else:
        print(f"Failed to update task {task_id} status: {response.content}")




@app.route('/run_indexer', methods=['POST'])
def run_indexer_command():
    data = request.json
    print(data)
    type = data['contenttype']
    org = data['org']
    repo = data.get('repo')
    task_id = f"{type}_{org}_{repo}"

    if type == 'webpage':

        command = f"kb_indexer web pipeline"


        #command = "python3 -m indexers.entrypoint api pipeline && python3 -m indexers.entrypoint web pipeline"    ##todo run on local

    elif type == 'api':
        command = f"kb_indexer api pipeline"


    elif type == 'dataset':
        if org == 'SeaDataNet':
            command = f"kb_indexer {type} -r 'SeaDataNet EDMED' pipeline &&" \
                        f"kb_indexer {type} -r 'SeaDataNet CDI' pipeline"
        else:
            command = f"kb_indexer {type} -r {org} pipeline"
    else:
        if repo == 'both':
            command = f"kb_indexer {type} -r Github pipeline &&" \
                        f"kb_indexer {type} -r Kaggle pipeline"

            #command = f"python3 -m indexers.entrypoint {type} -r Github pipeline &&" \
            #          f"kb_indexer {type} -r Kaggle pipeline"
        else:
            command = f"kb_indexer {type} -r {repo} pipeline"

            #command = f"python3 -m indexers.entrypoint {type} -r {repo} pipeline"

    executor.submit(run_process, command, task_id)
    return jsonify({"status": "success"}), 200


@app.route('/run_indexer_all', methods=['POST'])
def run_indexer_command_all():
    data = request.json
    org = data['org']
    task_id = 'all'
    command = f"kb_indexer web pipeline &&"\
                f"kb_indexer api pipeline &&"\
                f"kb_indexer notebook -r Github pipeline &&" \
              f"kb_indexer notebook -r Kaggle pipeline &&" \
            f"kb_indexer dataset pipeline"

    ##todo have not set the command of running all.
    executor.submit(run_process, command, task_id)
    return jsonify({"status": "success"}), 200






@app.route('/editing_json', methods=['POST'])
def editing_json():
    data = request.get_json()
    file_name = data.get('file_name')
    new_data = data.get('data')
    path = os.getcwd()

    path = f'{path}/indexers'

    print(path)

    if not file_name or not new_data:
        return jsonify({'error': 'Missing file_name or data'}), 400

    try:
        file_path = f'{path}/config.json'

        with open(file_path, 'w') as file:
            lock_file(file, 'w')  # adding a write lock
            file.write(json.dumps(new_data, indent=4))
            unlock_file(file)  # unlock
    except Exception as e:
        return jsonify({'error': str(e)}), 500


    with open(file_path, 'r') as config_file:
        config_data = json.load(config_file)
    domain_essential_variables = config_data.get('dataset', {}).get('json', {}).get('domain_essential_variables.json', {})
    domain_vocabularies = config_data.get('dataset', {}).get('json', {}).get('domain_vocabularies.json',
                                                                                {})
    metadata_schema = config_data.get('dataset', {}).get('json', {}).get('metadata_schema.json',
                                                                                    {})
    RI_domains = config_data.get('dataset', {}).get('json', {}).get('RI_domains.json',
                                                                                    {})
    RI_synonyms = config_data.get('dataset', {}).get('json', {}).get('RI_synonyms.json',
                                                                                    {})
    ResearchInfrastructures = config_data.get('webpage', {}).get('json', {}).get('ResearchInfrastructures.json',
                                                                                    {})

    files_to_update = [
        {'path': f'{path}/dataset/data_sources/domain_essential_variables.json', 'data': domain_essential_variables},
        {'path': f'{path}/dataset/data_sources/domain_vocabularies.json', 'data': domain_vocabularies},
        {'path': f'{path}/dataset/data_sources/metadata_schema.json', 'data': metadata_schema},
        {'path': f'{path}/dataset/data_sources/RI_domains.json', 'data': RI_domains},
        {'path': f'{path}/dataset/data_sources/RI_synonyms.json', 'data': RI_synonyms},
        {'path': f'{path}/web/data_sources/ResearchInfrastructures.json', 'data': ResearchInfrastructures}
    ]

    # 循环更新每个小文件
    for file_info in files_to_update:
        try:
            with open(file_info['path'], 'w') as file:
                json.dump(file_info['data'], file, indent=4)
            print(f"{file_info['path']} files updated")
        except Exception as e:
            print(f"error happened at file {file_info['path']} : {e}")
            return jsonify({'error': str(e)}), 500
    return jsonify({'message': 'Config updated successfully'}), 200






@app.route('/editing_notebook_data_sources', methods=['POST'])
def editing_notebook_data_sources():
    data = request.get_json()
    file_name = data.get('file_name')
    new_data = data.get('data')
    path = os.getcwd()

    if not file_name or not new_data:
        return jsonify({'error': 'Missing file_name or data'}), 400

    try:
        file_path = f'{path}/notebook/data_sources/envri_queries.csv'
        print(file_path)
        csv_data = new_data.replace('\\n', '\n')
        csv_reader = csv.reader(StringIO(csv_data))
        csv_rows = [row for row in csv_reader]
        with open(file_path, 'w') as file:
            lock_file(file, 'w')  # lock
            writer = csv.writer(file)
            writer.writerows(csv_rows)
            unlock_file(file)  # unlock
        return jsonify({'message': 'Config updated successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 409



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005)
