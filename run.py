from flask import Flask, request, session, url_for
from twilio.twiml.messaging_response import MessagingResponse
import json
import deliver
import MySQL
import darkskyreq
import phonenumbers
from datetime import datetime
import pytz
import os

SECRET_KEY = os.environ['SURVEY_SECRET_KEY']
app = Flask(__name__)
app.config.from_object(__name__)


@app.route("/sms", methods=['GET', 'POST'])
def incoming_sms():
    resp = MessagingResponse()

    nowt = datetime.now

    body = str(request.values.get('Body', None))
    num = request.values.get('From', None)
    num = phonenumbers.parse(num, None)
    num = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL)

    command = body.lower().split()[0].replace(':', '')

    db = MySQL.Database('users')
    db.execute("SELECT * FROM information")

    # Responds with a list of actions users can take
    if command == "actions" or command == "action":
        resp.message(
            "List of commands:\n"
            "TIME: Reply 'time' followed by the time you'd like to receive your daily update. 'Time 8am' to get your "
            "update at 8:00am.\n"
            "LOCATION: To change your location respond to the number with 'location' followed by your new location. "
            "'Location Richmond, VA' (you may also use your zip code, address, or a nearby landmark).\n"
            "WEATHER: To get a current weather update reply to the number with 'weather'.\n"
            "You can respond to the number with feedback or to get in touch with Delaney Kassab at any time. Just "
            "reply with whatever you have to say!\n"
            "To stop receiving messages at any time just reply 'STOP'.")

    # Changes user's location
    elif command == "location":
        location = body.lower().replace('location', '')
        usr = db.usr(num, 'byPhone')
        usr.location = location
        w = darkskyreq.Weather(usr.location)
        if w.getcoords() is None:
            resp.message("We couldn't find that location. Please type \"location\" followed by a valid location.")
        else:
            address = w.getaddress()
            tz = w.getweather().timezone
            resp.message("Your new location has been set: " + address)
            db.execute("UPDATE information SET location = '%s' WHERE customer_id = %s" % (location, usr.customer_id))
            db.execute("UPDATE information SET timezone = '%s' WHERE customer_id = %s" % (tz, usr.customer_id))
            db.commit()

    # Sends current conditions to user
    elif command == "weather":
        usr = db.usr(num, 'byPhone')
        deliver.sendWeather(usr.customer_id)

    # Sign up a new user via sms signup
    elif command == 'weathermywardrobe' or 'question_id' in session:

        with open('questions.json', 'r') as f:
            survey = json.load(f)
        if 'question_id' in session:
            resp.redirect(url_for('answer',
                                  question_id=session['question_id']))
        else:
            db.addnum(num)
            welcome_user(resp.message)
            redirect_to_first_question(resp, survey)

    # Changes the time the user receives the message
    elif command == "time":
        time = str(body.lower().replace('time', '').replace(' ', ''))
        usr = db.usr(num, 'byPhone')
        if 'a' in time or 'p' in time:
            if 'm' not in time:
                time += 'm'
            if ':' in time:
                try:
                    t = datetime.strptime(time, "%I:%M%p")
                    db.execute("UPDATE information SET usr_time = '%s' WHERE customer_id = %s" % (
                        t.strftime("%H:%M"), usr.customer_id))
                    resp.message(t.strftime("New time set for %I:%M%p"))
                except Exception as e:
                    print(e)
                    resp.message(
                        "Oops, you may have misformatted your time. Please double check the time you sent and reply "
                        "\"time \" followed by time you would like to set.")
            else:
                try:
                    t = datetime.strptime(time, "%I%p")
                    db.execute("UPDATE information SET usr_time = '%s' WHERE customer_id = %s" % (
                        t.strftime("%H:%M"), usr.customer_id))
                    resp.message(t.strftime("New time set for %I:%M%p"))
                except Exception as e:
                    print(e)
                    resp.message(
                        "Oops, you may have misformatted your time. Please double check the time you sent and reply "
                        "\"time \" followed by the time you would like to set.")
        else:
            resp.message("Make sure you include am or pm. Reply \"time \" followed by the time you would like to set.")
        db.commit()

    # if none of the above are true (there is no command), assumes the message is feedback and saves it to
    # logs/FeedbackLog.json. Also sends a message to me with the feedback, phone number, and first and last name.
    else:
        usr = db.usr(num, 'byPhone')
        msg = "New feedback from %s %s %s: %s" % (usr.first_name, usr.last_name, usr.phone, body)
        deliver.send('8049288208', msg)

        resp.message("Your feedback has been recorded. Thank you!")

        with open('logs/FeedbackLog.json', 'a', encoding='utf-8') as f:
            json.dump(msg, f, ensure_ascii=False, indent=4)
            f.write("\n")

    # logs everything sent to the number in logs/conversationLog.json
    with open('logs/conversationLog.json', 'a', encoding='utf-8') as f:
        conv = 'Message from %s at ' % (num) + nowt(pytz.timezone('America/New_York')).strftime(
            "%b %d at %I:%M%p: ") + body
        json.dump(conv, f, ensure_ascii=False, indent=4)
        f.write('\n')

    return str(resp)


@app.route('/question/<question_id>')
def question(question_id):
    with open('questions.json', 'r') as f:
        survey = json.load(f)
    question = survey[int(question_id)]
    session['question_id'] = question_id
    return sms_twiml(question)


@app.route('/answer/<question_id>', methods=['POST'])
def answer(question_id):
    body = str(request.values.get('Body', None))

    num = request.values.get('From', None)
    num = phonenumbers.parse(num, None)
    num = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL)

    db = MySQL.Database('users')

    question_id = int(question_id)

    with open('questions.json', 'r') as f:
        survey = json.load(f)

    if db.addUsr(num, question_id, body):
        return sms_twiml("I wasn't able to find that location. Try double checking your spelling.")
    try:
        next_question = survey[question_id + 1]
        return redirect_twiml(next_question)
    except:
        return goodbye_twiml()


def goodbye_twiml():
    resp = MessagingResponse()
    num = request.values.get('From', None)
    num = phonenumbers.parse(num, None)
    num = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL)

    db = MySQL.Database('users')
    usr = db.usr(num, 'byPhone')
    resp.message(
        "Hey there, %s! Thank you for signing up for weather updates with Weather My Wardrobe!\n\n"
        "You'll receive your personalized weather update at 6:30 am every day!\n"
        "If you would like to change this, or your location, reply 'actions' to learn how, along with some other "
        "useful information!" % usr.first_name)
    deliver.sendWeather(usr.customer_id, 'mms')
    if 'question_id' in session:
        del session['question_id']
    return str(resp)


def redirect_twiml(question):
    with open('questions.json', 'r') as f:
        survey = json.load(f)
    resp = MessagingResponse()
    resp.redirect(url=url_for('question', question_id=survey.index(question)),
                  method='GET')
    return str(resp)


def sms_twiml(question):
    resp = MessagingResponse()
    resp.message(question)
    return str(resp)


def redirect_to_first_question(resp, survey):
    first_question = survey[0]
    first_question_url = url_for('question', question_id=survey.index(first_question))
    resp.redirect(url=first_question_url, method='GET')


def welcome_user(send_function):
    welcome_text = 'Thank you for signing up for weather updates with with Weather My Wardrobe! To finish signing up ' \
                   'just answer the following questions:'
    send_function(welcome_text)
