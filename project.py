# import modules used in this application
from flask import Flask, render_template
from flask import request, redirect, jsonify, url_for, flash
from sqlalchemy import create_engine, asc
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import scoped_session
from database_setup import Base, Country, University, User
from flask import session as login_session
import random
import string
from functools import wraps
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests

app = Flask(__name__)

CLIENT_ID = json.loads(open('client_secrets.json', 'r').
                       read())['web']['client_id']
APPLICATION_NAME = "Restaurant Menu Application"


# Connect to Database and create database session
engine = create_engine('sqlite:///countryuniversitywithusers.db')
Base.metadata.bind = engine

session = scoped_session(sessionmaker(bind=engine))

# Create decorator function to simply the verification of user login status
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in login_session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

# Create anti-forgery state token
@app.route('/login')
def showLogin():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session['state'] = state
    # return "The current session state is %s" % login_session['state']
    return render_template('login.html', STATE=state)


@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_credentials = login_session.get(
        'credentials')
    stored_gplus_id = login_session.get(
        'gplus_id')
    if stored_credentials is not None and gplus_id == stored_gplus_id:
        response = make_response(
            json.dumps('Current user is already connected.'),
             200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']
    # ADD PROVIDER TO LOGIN SESSION
    login_session['provider'] = 'google'

    # see if user exists, if it doesn't make a new one
    user_id = getUserID(data["email"])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += '<style = "width: 300px; height: 300px;border-radius: 150px;\
    -webkit-border-radius: 150px;-moz-border-radius: 150px;"> '
    flash("you are now logged in as %s" % login_session['username'])
    print "done!"
    return output

# User Helper Functions
def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None

# DISCONNECT - Revoke a current user's token and reset their login_session
@app.route('/gdisconnect')
def gdisconnect():
    # Only disconnect a connected user.
    credentials = login_session.get('credentials')
    if credentials is None:
        response = make_response(
            json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    access_token = credentials.access_token
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % access_token
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    if result['status'] != '200':
        # For whatever reason, the given token was invalid.
        response = make_response(
            json.dumps('Failed to revoke token for given user.'), 400)
        response.headers['Content-Type'] = 'application/json'
        return response


# JSON APIs to view Restaurant Information
@app.route('/country/<int:country_id>/university/JSON')
def countryUniversityJSON(country_id):
    country = session.query(Country).filter_by(id=country_id).one()
    schools = session.query(University).filter_by(
        country_id=country_id).all()
    return jsonify(Universities=[i.serialize for i in schools])


@app.route('/country/<int:country_id>/university/<int:university_id>/JSON')
def menuItemJSON(country_id, university_id):
    school = session.query(University).filter_by(id=university_id).one()
    return jsonify(school=school.serialize)


@app.route('/country/JSON')
def countriesJSON():
    countries = session.query(Country).all()
    return jsonify(countries=[r.serialize for r in countries])


# Show all countries
@app.route('/')
@app.route('/country/')
def showCountries():
    countries = session.query(Country).order_by(asc(Country.name))
    if 'username' not in login_session:
        return render_template('publiccountries.html', countries=countries)
    else:
        return render_template('countries.html', countries=countries)

# Create a new country
@app.route('/country/new/', methods=['GET', 'POST'])
@login_required
def newCountry():
    if request.method == 'POST':
        newCountry = Country(
            name=request.form['name'], user_id=login_session['user_id'])
        session.add(newCountry)
        flash('New Country %s Successfully Created' % newCountry.name)
        session.commit()
        return redirect(url_for('showCountries'))
    else:
        return render_template('newcountry.html')

# Edit a country
@app.route('/country/<int:country_id>/edit/', methods=['GET', 'POST'])
@login_required
def editCountry(country_id):
    editedCountry = session.query(
        Country).filter_by(id=country_id).one()
    if editedCountry.user_id != login_session['user_id']:
        return """<script>function myFunction() {alert('You are not authorized to 
        edit this country.Please create your own country in order to edit.');}
        </script><body onload='myFunction()''>"""
    if request.method == 'POST':
        if request.form['name']:
            editedCountry.name = request.form['name']
            flash('Country Successfully Edited %s' % editedCountry.name)
            return redirect(url_for('showCountries'))
    else:
        return render_template('editcountry.html', country=editedCountry)


# Delete a country
@app.route('/country/<int:country_id>/delete/', methods=['GET', 'POST'])
@login_required
def deleteCountry(country_id):
    countryToDelete = session.query(Country).filter_by(id=country_id).one()
    if countryToDelete.user_id != login_session['user_id']:
        return """<script>function myFunction()
        {alert('You are not authorized to delete this country. 
        Please create your own country in order to delete.');}
        </script><body onload='myFunction()''>"""
    if request.method == 'POST':
        session.delete(countryToDelete)
        flash('%s Successfully Deleted' % countryToDelete.name)
        session.commit()
        return redirect(url_for('showCountries'))
    else:
        return render_template('deletecountry.html', country=countryToDelete)

# Show a list of universities in a country
@app.route('/country/<int:country_id>/')
@app.route('/country/<int:country_id>/university/')
def showUniversities(country_id):
    country = session.query(Country).filter_by(id=country_id).one()
    creator = getUserInfo(country.user_id)
    schools = session.query(University).filter_by(
        country_id=country_id).all()
    if 'username' not in login_session or\
     creator.id != login_session['user_id']:
        return render_template('publicuniversity.html', 
        schools=schools, country=country, creator=creator)
    else:
        return render_template('university.html', schools=schools, 
                               country=country, creator=creator)


# Create a new university
@app.route('/country/<int:country_id>/university/new/', 
           methods=['GET', 'POST'])
def newUniversity(country_id):
    if 'username' not in login_session:
        return redirect('/login')
    country = session.query(Country).filter_by(id=country_id).one()
    if login_session['user_id'] != country.user_id:
        return """<script>function myFunction() {alert
        ('You are not authorized to add universities to this country. 
        Please create your own country in order to add universities.');}
        </script><body onload='myFunction()''>"""
    if request.method == 'POST':
        newUni = University(name=request.form['name'], 
                            description=request.form['description'], 
                            country_id=country_id, user_id=country.user_id)
        session.add(newUni)
        session.commit()
        flash('New University %s Successfully Created' % (newUni.name))
        return redirect(url_for('showUniversities', country_id=country_id))
    else:
        return render_template('newuniversity.html', country_id=country_id)

# Edit a university
@app.route('/country/<int:country_id>/university/<int:university_id>/edit', 
           methods=['GET', 'POST'])
def editUniversity(country_id, university_id):
    if 'username' not in login_session:
        return redirect('/login')
    editedUni = session.query(University).filter_by(id=university_id).one()
    country = session.query(Country).filter_by(id=country_id).one()
    if login_session['user_id'] != country.user_id:
        return """<script>function myFunction() 
        {alert('You are not authorized to edit universities to this country. 
        Please create your own country in order to edit universities.');}
        </script><body onload='myFunction()''>"""
    if request.method == 'POST':
        if request.form['name']:
            editedUni.name = request.form['name']
        if request.form['description']:
            editedUni.description = request.form['description']
        session.add(editedUni)
        session.commit()
        flash('University Successfully Edited')
        return redirect(url_for('showUniversities', country_id=country_id))
    else:
        return render_template('edituniversity.html', country_id=country_id, 
                               university_id=university_id, uni=editedUni)


# Delete a university
@app.route('/country/<int:country_id>/university/<int:university_id>/delete', 
           methods=['GET', 'POST'])
def deleteUniversity(country_id, university_id):
    if 'username' not in login_session:
        return redirect('/login')
    country = session.query(Country).filter_by(id=country_id).one()
    uniToDelete = session.query(University).filter_by(id=university_id).one()
    if login_session['user_id'] != country.user_id:
        return """"<script>function myFunction() 
        {alert('You are not authorized to delete universities to this country. 
        Please create your own country in order to delete universities.');}
        </script><body onload='myFunction()''>"""
    if request.method == 'POST':
        session.delete(uniToDelete)
        session.commit()
        flash('University Successfully Deleted')
        return redirect(url_for('showUniversities', country_id=country_id))
    else:
        return render_template('deleteuniversity.html', 
        country_id = country_id, uni=uniToDelete)


# Disconnect based on provider
@app.route('/disconnect')
def disconnect():
    if 'provider' in login_session:
        if login_session['provider'] == 'google':
            gdisconnect()
            del login_session['gplus_id']
            # del login_session['credentials']
        if login_session['provider'] == 'facebook':
            fbdisconnect()
            del login_session['facebook_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        del login_session['user_id']
        del login_session['provider']
        flash("You have successfully been logged out.")
        return redirect(url_for('showCountries'))
    else:
        flash("You were not logged in")
        return redirect(url_for('showCountries'))

app.secret_key = 'super_secret_key'

if __name__ == '__main__':
    app.debug = True

