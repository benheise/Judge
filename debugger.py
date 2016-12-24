#!/usr/bin/python

from urlparse import urlparse
from ftplib import FTP
from StringIO import StringIO
import sqlite3, dns.resolver, requests
from dns.exception import DNSException
import difflib

import os.path
from threading import Thread
from time import sleep

from flask import Flask, render_template, redirect, url_for, request, flash
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, validators
from flask_wtf.file import FileField, FileRequired
from werkzeug.utils import secure_filename

# Application settings
app = Flask(__name__)
app.secret_key = 'dev key'


# Database functions
def database_create():
    """
    Create the backend ./data/debugger.db sqlite database
    """
    db = database_connect()
    with app.open_resource('./data/schema.sql', mode='r') as f:
        db.cursor().executescript(f.read())
    db.commit()

def database_populate():
    """
    Populate the database.
    """
    db = database_connect()
    with app.open_resource('./data/default/data.sql', mode='r') as f:
        db.cursor().executescript(f.read())
    db.commit()

def database_connect():
    """
    Connect with the backend ./debugger.db sqlite database and return the
    connection object.
    """
    try:
        # set the database connectiont to autocommit w/ isolation level
        conn = sqlite3.connect('./data/debugger.db')
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        print "Error connecting to database. Must run 'flask setup' prior to running."
        sys.exit()

def execute_db_query(query, args=None):
    """
    Execute the supplied query on the provided db conn object
    with optional args for a paramaterized query.
    """
    conn = database_connect()
    cur = conn.cursor()
    if(args):
        cur.execute(query, args)
    else:
        cur.execute(query)
    conn.commit()
    results = cur.fetchall()
    cur.close()
    conn.close()
    return results

# Functions to be used in Jinja templates
@app.context_processor
def utility_processor():    
    return dict(execute_db_query=execute_db_query)
       
@app.cli.command('setup')
def setup():
    if os.path.isfile('data/debugger.db'):
        os.remove('data/debugger.db')
    print 'Initializing database...'
    database_create()
    print 'Done.'

@app.cli.command('populate')
def populate():
    print 'Populating database...'
    database_populate()
    print 'Done.'

class AddTeamForm(FlaskForm):
    team_name = StringField('Team Name', [validators.Length(min=1, max=50)])

class AddDNSServiceForm(FlaskForm): 
    team_name = SelectField('Team')
    service_name = StringField('Service Name', [validators.Length(min=1, max=50)])
    service_connection = StringField('DNS Server IP', [validators.IPAddress()])
    service_request = StringField('DNS Lookup Hostname', [validators.Length(min=1, max=50)])
    service_expected_result = StringField('Expected IP Result', [validators.IPAddress()])

class AddWebServiceForm(FlaskForm):
    team_name = SelectField('Team')
    service_name = StringField('Service Name', [validators.Length(min=1, max=50)])
    service_url = StringField('HTTP(S)/FTP URL', [validators.URL()])
    service_file = FileField('Expected File', [FileRequired()])

@app.route('/configure', methods=['GET'])
def configure(): 
    forms = {}
    forms['addTeamForm'] = AddTeamForm(request.form, csrf_enabled=False)
    forms['addDNSServiceForm'] = AddDNSServiceForm(request.form, csrf_enabled=False)
    forms['addWebServiceForm'] = AddWebServiceForm(request.form, csrf_enabled=False)
    choices = [(team['team_id'], team['team_name']) for team in execute_db_query('select team_id, team_name from team')]
    forms['addDNSServiceForm'].team_name.choices = choices
    forms['addWebServiceForm'].team_name.choices = choices
    return render_template('configure.html', forms=forms)

@app.route('/team/add', methods=['POST'])
def add_team():
    form = AddTeamForm(csrf_enabled=False)
    if form.validate_on_submit():
        execute_db_query('INSERT INTO team(team_name) VALUES(?)', [form.team_name.data])
    else:
        flash('Form not validated')
    return redirect(url_for('configure'))

@app.route('/team/remove', methods=['POST'])
def remove_team():
    # remove team
    return redirect(url_for('configure'))

@app.route('/service/dns/add', methods=['POST'])
def add_dns_service():
    form = AddDNSServiceForm(csrf_enabled=False)
    if form.validate_on_submit():
        service_type_id = execute_db_query('select service_type_id from service_type where service_type_name = ?', [service_type_name])[0]['service_type_id']
        team_id = execute_db_query('select team_id from team where team_name = ?', [team_name])[0]['team_id']
        execute_db_query('INSERT INTO service(service_type_id, team_id, service_name, service_connection, service_request, service_expected_result) VALUES(?, ?, ?, ?, ?, ?)', [service_type_id, team_id, form.service_name.data, form.service_connection.data, form.service_request.data, form.service_expected_result.data])
    else:
        flash('Form not validated')
    return redirect(url_for('configure'))

@app.route('/service/web/add', methods=['POST'])
def add_web_service():
    form = AddWebServiceForm(csrf_enabled=False)
    if form.validate_on_submit():
        team_name = form.team_name.data
        service_name = form.service_name.data
        
        service_url = urlparse(form.service_url.data)
        service_type_name = service_url.scheme
        service_connection = service_url.netloc

        filename = secure_filename(form.service_file.data.filename)
        form.service_file.data.save('data/uploads/' + filename)
        service_request = service_url.path
        service_expected_result = filename
        
        service_type_id = execute_db_query('select service_type_id from service_type where service_type_name = ?', [service_type_name])[0]['service_type_id']
        team_id = execute_db_query('select team_id from team where team_name = ?', [team_name])[0]['team_id']
        execute_db_query('INSERT INTO service(service_type_id, team_id, service_name, service_connection, service_request, service_expected_result) VALUES(?, ?, ?, ?, ?, ?)', [service_type_id, team_id, service_name, service_connection, service_request, service_expected_result])
    else:
        flash('Form not validated')
    return redirect(url_for('configure'))

@app.route('/errors')
def errors():
    return render_template('errors.html')

@app.route('/scoreboard')
def scoreboard():
    return render_template('scoreboard.html')

@app.route('/')
def home():
    return redirect(url_for('scoreboard'))

def poll():
    for service in execute_db_query('select * from service where service_active = 1'):
        row = execute_db_query('select * from service_type join service ON (service_type.service_type_id = service.service_type_id) where service.service_type_id = ?', [service['service_type_id']])[0]
        if row:
            id = service['service_id']
            type = row['service_type_name']
            server = service['service_connection']
            request = service['service_request']
            eresult = service['service_expected_result']
            match = False
            if type == 'dns':
                result = ''
                try:
                    resolv = dns.resolver.Resolver()
                    resolv.nameservers = [server]
                    resolv.timeout = 8
                    resolv.lifetime = 8
                    answers = resolv.query(request, 'A')
                    for rdata in answers:
                        result = rdata.to_text()
                except DNSException:
                    execute_db_query('insert into error(service_id, error_message) values(?,?)', [id, 'DNS Timeout on request for: ' + request + ' using server: ' + server])
                if result == eresult:
                    match = True
                else:
                    execute_db_query('insert into error(service_id,error_message) values(?,?)', [id, 'DNS Request result: ' + result + ' did not match expected: ' + eresult])

            elif type == 'http' or type == 'https':
                try:
                    result = requests.get(type + '://' + server + request, timeout=2).text
                    if os.path.isfile(eresult):
                        upload = open(eresult, 'r')
                        eresult = upload.read()
                        upload.close()
                        # Only comparing first 10 lines for now. Have no good way to compare dynamic portions of a webpage.
                        one = eresult.splitlines(1)[0:10]
                        two = result.splitlines(1)[0:10]
                        if one == two:
                            match = True
                        else:
                            diff = difflib.unified_diff(one, two)
                            execute_db_query('insert into error(service_id,error_message) values(?,?)', [id, 'HTTP(S) Request result did not match expected. Diff: \n' + ''.join(diff)])
                    else:
                        execute_db_query('insert into error(service_id, error_message) values(?,?)', [id, 'Local filename for expected result: ' + eresult + ' does not exist.'])
                except requests.exception.RequestException as e:
                    execute_db_query('insert into error(service_id,error_message) values(?,?)', [id, 'HTTP(S) Request resulted in exception: ' + e]) 
 
            elif type == 'ftp':
                ftp = FTP(server)
                ftp.login()
                resultStringIO = StringIO()
                ftp.retrbinary('RETR ' + request, resultStringIO.write)
                result = resultStringIO.getvalue()
                if result == eresult:
                    match = True
                else:
                    execute_db_query('insert into error(service_id,error_message) values(?,?)', [id, 'FTP Request result: ' + result + ' did not match expected: ' + eresult])
            if match:
                execute_db_query('insert into poll(poll_score,service_id) values(1,?)', [id])
            else:
                execute_db_query('insert into poll(poll_score,service_id) values(0,?)', [id])

def poll_forever():
    while True:
        try:
            sleep(10)
            poll()
        except:
            pass
                            

if __name__ == "__main__":
    thread = Thread(target=poll_forever)
    thread.setDaemon(True)
    thread.start()
    app.run(host='0.0.0.0')

