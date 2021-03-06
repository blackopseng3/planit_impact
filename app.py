import os, json, boto, zipfile, re, pdb
from boto.s3.key import Key
from flask import Flask, redirect, request, render_template, Response
from werkzeug import secure_filename

from flask.ext.heroku import Heroku
from flask.ext.sqlalchemy import SQLAlchemy

from xml.etree import ElementTree
from StringIO import StringIO

PROJECT_DIR = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))

try:
    from setup_local import *
except:
    cache = None
    BUCKET_STREAM = False
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME') or 'planit-impact-models'
    SQLALCHEMY_DATABASE_URI = 'postgres://hackyourcity@localhost/planit'

#----------------------------------------
# initialization
#----------------------------------------

app = Flask(__name__)
heroku = Heroku(app)
db = SQLAlchemy(app)

app.config.update(
    DEBUG = True,
    # For local development, uncomment and put in your own user name
    SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI
)

# Might not need these anymore? What config key does boto use?
app.config.setdefault('AWS_ACCESS_KEY_ID', AWS_ACCESS_KEY_ID)
app.config.setdefault('AWS_SECRET_ACCESS_KEY', AWS_SECRET_ACCESS_KEY)
app.config.setdefault('S3_BUCKET_NAME', AWS_SECRET_ACCESS_KEY)

#----------------------------------------
# models
#----------------------------------------

class Project(db.Model):
    __tablename__ = 'project'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Unicode)
    description = db.Column(db.Unicode)
    s3_url = db.Column(db.Unicode)
    s3_name = db.Column(db.Unicode)
    settings_json = db.Column(db.Unicode)

    def upload_to_s3(self, name, localpath):
        conn = boto.connect_s3(AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
        mybucket = conn.get_bucket(S3_BUCKET_NAME)
        k = Key(mybucket)
        k.key = name
        k.set_contents_from_filename(localpath)
        mybucket.set_acl('public-read', name)
        conn.close()
        self.s3_name = name
        self.s3_url = 'https://s3.amazonaws.com/%s/'% S3_BUCKET_NAME + name

    def download_from_s3(self):
        conn = boto.connect_s3(AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
        mybucket = conn.get_bucket(S3_BUCKET_NAME)
        k = Key(mybucket)
        k.key = self.s3_name
        content = k.get_contents_as_string()
        conn.close()
        return content

    @property
    def kmz_url(self):
        return self.s3_url


class ThreeDeeModel(db.Model):
    __tablename__ = 'three_dee_model'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Unicode)
    description = db.Column(db.Unicode)
    localpath = db.Column(db.Unicode)
    latitude = db.Column(db.Unicode)
    longitude = db.Column(db.Unicode)
    s3_url = db.Column(db.Unicode)

    def __init__(self, name, description, localpath):
        self.name = name
        self.description = description
        self.localpath = localpath

    def open_model(self):
        z = zipfile.ZipFile(self.localpath)
        z.extractall('tmp')

    def get_lat_lon_from_model(self):
        try:
            kml = open('tmp/doc.kml','r').read()
            match = re.search('<latitude>(.*)</latitude>', kml)
            self.latitude = match.group(1)
            match = re.search('<longitude>(.*)</longitude>', kml)
            self.longitude = match.group(1)
        except:
            pass

    def upload_to_s3(self):
        conn = boto.connect_s3(AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
        mybucket = conn.get_bucket(S3_BUCKET_NAME)
        k = Key(mybucket)
        k.key = self.name
        k.set_contents_from_filename(self.localpath)
        conn.close()
        self.s3_url = 'https://s3.amazonaws.com/%s/'% S3_BUCKET_NAME + self.name

#----------------------------------------
# controllers
#----------------------------------------

@app.route("/")
@app.route("/index")
@app.route("/index.html")
def index():
    return render_template('index.html')

@app.route("/about")
@app.route("/about.html")
def about():
    return render_template('about.html')

@app.route("/features")
@app.route("/features.html")
def features():
    return render_template('features.html')

@app.route("/howitworks")
@app.route("/howitworks.html")
def howitworks():
    return render_template('howitworks.html')

@app.route("/demo", methods=['GET', 'POST'])
def demo():
    if request.method == 'POST':
        model = Project()
        model.name = request.form['name']
        model.description = request.form['description']

        db.session.add(model)
        db.session.commit()

    all_projects = Project.query.order_by(Project.id.desc()).all()

    return render_template('demo_projects.html', all_projects=all_projects)

@app.route("/projects/<model_id>/report")
def report(model_id):
    model = Project.query.filter_by(id=model_id).first()
    storm_water = 0
    try:
        st = json.loads(model.settings_json)
    except Exception:
        st = {}

    rv = (st.get('c1', 0) * st.get('c1_area_p', 0) +
          st.get('c2', 0) * st.get('c2_area_p', 20) +
          st.get('c3', 0) * st.get('c3_area_p', 10) +
          st.get('c4', 0) * st.get('c4_area_p', 25) +
          st.get('c5', 0) * st.get('c5_area_p', 30) +
          st.get('c6', 0) * st.get('c6_area_p', 15)) / 100
    pj = 0.9
    p = 38.86
    a = 98000
    r = p * pj * rv

    storm_water = (r/12) * a * 7.48

    return render_template('explore.html', model=model, storm_water=int(storm_water))


def float_or_zero(int_str):
    try:
        flt = float(int_str) or 0
        flt = max(flt, 0)
        flt = min(flt, 1)

        return flt
    except:
        return 0

@app.route("/projects/<model_id>/delete", methods=['POST'])
def project_delete(model_id):
    model = Project.query.filter_by(id=model_id).first()

    db.session.delete(model)
    db.session.commit()

    all_projects = Project.query.order_by(Project.id.desc()).all()
    return render_template('demo_projects.html', all_projects=all_projects)

@app.route("/projects/<model_id>/", methods=['GET', 'POST'])
def project(model_id):
    model = Project.query.filter_by(id=model_id).first()

    if request.method == 'POST':
        c1 = float_or_zero(request.form.get('c1', 0.3))
        c2 = float_or_zero(request.form.get('c2', 0.9))
        c3 = float_or_zero(request.form.get('c3', 0.1))
        c4 = float_or_zero(request.form.get('c4', 0.5))
        c5 = float_or_zero(request.form.get('c5', 0.15))
        c6 = float_or_zero(request.form.get('c6', 0.75))

        kmz_file = request.files.get('file')
        if kmz_file:
            save_kmz(model, kmz_file)
            c1 = 0.3
            c2 = 0.9
            c3 = 0.1
            c4 = 0.5
            c5 = 0.15
            c6 = 0.75

        model.settings_json = json.dumps({
            'c1': c1,
            'c2': c2,
            'c3': c3,
            'c4': c4,
            'c5': c5,
            'c6': c6,
            'c1_area_p': 0,
            'c2_area_p': 20,
            'c3_area_p': 10,
            'c4_area_p': 25,
            'c5_area_p': 30,
            'c6_area_p': 15
        })

        db.session.add(model)
        db.session.commit()

        if request.form.get('report_action'):
            return redirect('/projects/%s/report' % model.id)

    try:
        settings_json = json.loads(model.settings_json)
    except:
        settings_json = {}

    if not settings_json:
        if model.kmz_url:
            settings_json = { 'c1': 0.3, 'c2': 0.9, 'c3': 0.1, 'c4': 0.5, 'c5': 0.15, 'c6': 0.75,
                              'c1_area_p': 0,
                              'c2_area_p': 20,
                              'c3_area_p': 10,
                              'c4_area_p': 25,
                              'c5_area_p': 30,
                              'c6_area_p': 15, }

    return render_template('project.html', model=model, settings=settings_json)


def save_kmz(model, kmz_file):
    if '.kmz' in kmz_file.filename:
        filename = secure_filename(kmz_file.filename)
        try:
            os.mkdir('tmp')
        except Exception as e:
            pass
        filepath = 'tmp/'+filename
        kmz_file.save(filepath)

        model.upload_to_s3(filename, filepath)
        db.session.add(model)
        db.session.commit()

@app.route("/projects/<model_id>/overlays/storm_water")
def project_overlay(model_id):
    model = Project.query.filter_by(id=model_id).first()

    try:
        params = json.loads(model.settings_json)
    except:
        params = {}

    path = os.path.abspath(os.path.join(PROJECT_DIR, 'static/models/overlay.kml'))

    tree = ElementTree.parse(path)
    root = tree.getroot()

    for placemark in root.iter('{http://www.opengis.net/kml/2.2}Placemark'):
        c = placemark.get('class')
        sub_value = params.get(c)

        if sub_value is not None:
            color = placemark.find('./{http://www.opengis.net/kml/2.2}Style/{http://www.opengis.net/kml/2.2}PolyStyle/{http://www.opengis.net/kml/2.2}color')
            if color is not None:
                if sub_value < 0.5:
                    sub_value = 256 * (sub_value * 2)
                    sub_value = min(sub_value, 255)
                    sub_value = max(sub_value, 0)

                    color.text = 'ff00ff%02x' % sub_value
                else:
                    sub_value = 256 * (1 - (sub_value - 0.5) * 2)
                    sub_value = min(sub_value, 255)
                    sub_value = max(sub_value, 0)
                    color.text = 'ff00%02xff' % sub_value

    overlay = StringIO()
    tree.write(overlay)
    overlay.seek(0)

    return Response(overlay)


@app.route("/projects/<model_id>/kmz_upload", methods=['POST'])
def project_kmz_upload(model_id):
    model = Project.query.filter_by(id=model_id).first()

    if request.method == 'POST':
        save_kmz(model, request.files['file'])

    return ''

if __name__ == "__main__":
    app.run()