import io
import json
import uuid
import discord
from discord.ext import commands
from discord.ext import tasks
import os
from twilio.rest import Client
import threading
import requests
import traceback
# from dotenv import load_dotenv
# load_dotenv()

from flask import Flask, redirect, url_for, send_file, request, jsonify, request, send_file, Response, make_response, request, abort, current_app as app
from flask import send_file

app = Flask(__name__)

#Discord
token = "Discord Token Here"

#Twilio
account_sid = "Twilio SID Here"
auth_token = "Twilio Auth Token Here"

#API KEYS
weather_api = "weatherapi.com Key Here"
apininjakey = "api-ninjas Key Here"

#Instantiate the Twilio Client
twilioclient = Client(account_sid, auth_token)

#Instantiate the Discord Client
client = commands.Bot(command_prefix='!', self_bot=True)

defaultchannelid = None # Put your default channel ID to chat in here <3

myPhoneNumber = "Enter your whitelisted phone number here"
fromPhoneNumber = "Put the phone number given to you by Twilio here"

# Pending messages and files to send, really weird workaround because Discord gets mad when awaiting their methods outside of their asyncio loop and I don't want to rewrite the entire thing to use their asyncio loop.
messages = []
files = []


# This is what you need to set as the webhook for your Twilio number to receive messages.
@app.route('/sms', methods=['GET', 'POST'])
async def sms():
  await receiveSMS(request.form)
  return "Done", 200

#Start the Flask server in a new thread
threading.Thread(target=lambda: app.run(
    host="0.0.0.0", port=80, debug=True, use_reloader=False)).start()

#Converts a list of servers to a string to send back to the user
async def convertServerListToSMS(serverslist):
  finalString = 'Server List:'
  for server in serverslist:
    for serverID, serverName in server.items():
      finalString += f" || {serverID}, {serverName}"
  return finalString

#Converts a list of channels to a string to send back to the user
async def convertChannelListToSMS(channelList):
  finalString = 'Channel List:'
  for channel in channelList:
    for channelID, channelName in channel.items():
      finalString += f" || {channelID}, {channelName}"
  return finalString

#Commands

#Gets a list of servers the client is in
async def get_servers(content):
    print("Running getservers")
    servers = [{str(guild.id): str(guild.name)} for guild in client.guilds]
    return await convertServerListToSMS(servers)

#Gets a list of channels in a server, breaks if the server has too many channels : channels > 40, this includes private channels
async def get_channels(content):
    print("Running getchannels")
    guild_id = int(content.split()[1])
    guild = client.get_guild(guild_id)
    channels = [{str(channel.id): str(channel.name)} for channel in guild.text_channels]
    return await convertChannelListToSMS(channels)

#Sets the default channel to send messages to and receive messages from
async def set_channel(content):
    global defaultchannelid
    newid = int(content.split()[1])
    defaultchannelid = newid
    return f"Successfully set channel to {client.get_channel(newid).name}"

#Gets a random fact from uselessfacts.jsph.pl
async def get_random_fact(content):
    response = requests.request("GET", "https://uselessfacts.jsph.pl/api/v2/facts/random")
    return response.json()["text"]

#Gets the weather in a (city, country) using api-ninjas and weatherapi.com
async def get_weather(content):
    city, country = content.split()[1:3]
    headers = {'X-Api-Key': apininjakey}
    try:
        geolocation_response = requests.get(f"https://api.api-ninjas.com/v1/geocoding?city={city}&country={country}", headers=headers)
        geolocation_response.raise_for_status()
    except requests.exceptions.RequestException as err:
        print(f"Error occurred: {err}")
        return
    geolocation_data = geolocation_response.json()[0]
    latitude, longitude = geolocation_data["latitude"], geolocation_data["longitude"]
    try:
        weather_response = requests.get(f"http://api.weatherapi.com/v1/current.json?key={weather_api}&q={latitude},{longitude}&aqi=no")
        weather_response.raise_for_status()
    except requests.exceptions.RequestException as err:
        print(f"Error occurred: {err}")
        return
    temperature = weather_response.json()["current"]["temp_c"]
    return f"The temperature in {city} is {temperature} degrees celsius."

#Easy way of adding commands, just add a new key value pair to the dictionary with the key being the command and the value being the function to run
COMMANDS = {
    "!getservers": get_servers,
    "!getchannels": get_channels,
    "!setchannel": set_channel,
    "!fact": get_random_fact,
    "!weather": get_weather
}

#Checks if the message is a command, if it is, it runs the command and returns the result
async def checkForCommands(content):
    try:
        command = "!"+content.split()[0]
        func = COMMANDS.get(command)
        return await func(content) if func else False
    except Exception:
        traceback.print_exc()
        return None

#Gets called by the webhook data receiver when a message is received, adds the message to the queue to be sent to Discord through the client
async def receiveSMS(message):
    command = await checkForCommands(message["Body"])
    if command:
        if command is None or len(command) > 1600:
            await sendBackSMS("An error has happened while executing your command.")
        else:
            await sendBackSMS(command)
    elif message["From"] == myPhoneNumber:
        if message["Body"]:
            messages.append(message["Body"])
        media_url = message.get("MediaUrl0")
        if media_url:
            print(media_url)
            files.append(media_url)

#Initialize the client
@client.event
async def on_ready():
  print(f'We have logged in as {client.user}')
  myLoop.start()

#The loop that sends pending messages and files to the default channel
@tasks.loop(seconds = 0.1)
async def myLoop():
    channel = client.get_channel(defaultchannelid)
    if messages:
        await channel.send(messages.pop(0))
    elif files:
        headers = {'Authorization': f'Basic {os.getenv("IMAGE_AUTH")}=='}
        response = requests.get(files.pop(0), headers=headers)
        await channel.send(file=discord.File(io.BytesIO(response.content), "image.png"))

#Listens for messages from the Discord Client's end, if the message is in the default channel, it sends it to the phone number
@client.event
async def on_message(message):
    if message.author.bot or message.author == client.user or message.channel.id != defaultchannelid:
        return
    has_image = bool(message.attachments)
    message_content = f"{message.author.name}: {message.content}"
    await sendSMS(message_content, has_image, message)

#Sends a message to the phone number, if the message contains an image, it sends the image as well
async def sendSMS(messagestr, containsimage, message):
  if containsimage == True and message.content != "":
    twilioclient.messages.create(body=messagestr, from_=fromPhoneNumber, to=myPhoneNumber, media_url=message.attachments[0].url)
  elif containsimage == True:
    twilioclient.messages.create(from_=fromPhoneNumber, to=myPhoneNumber, media_url=message.attachments[0].url)
  else:
    twilioclient.messages.create(body=messagestr, from_=fromPhoneNumber, to=myPhoneNumber)

#Lazy 2nd function for commands, sends a message to the phone number
async def sendBackSMS(messagestr):
  twilioclient.messages.create(body=messagestr, from_=fromPhoneNumber, to=myPhoneNumber)

client.run(token)

if __name__ == '__main__':
  app.run(host='0.0.0.0', port=80)