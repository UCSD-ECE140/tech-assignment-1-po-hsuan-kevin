import os
import json
from dotenv import load_dotenv

import paho.mqtt.client as paho
from paho import mqtt
import time
from game import Game
from moveset import Moveset

# setting callbacks for different events to see if it works, print the message etc.
def on_connect(client, userdata, flags, rc, properties=None):
    """
        Prints the result of the connection with a reasoncode to stdout ( used as callback for connect )
        :param client: the client itself
        :param userdata: userdata is set when initiating the client, here it is userdata=None
        :param flags: these are response flags sent by the broker
        :param rc: stands for reasonCode, which is a code for the connection result
        :param properties: can be used in MQTTv5, but is optional
    """
    print("CONNACK received with code %s." % rc)


# with this callback you can see if your publish was successful
def on_publish(client, userdata, mid, properties=None):
    """
        Prints mid to stdout to reassure a successful publish ( used as callback for publish )
        :param client: the client itself
        :param userdata: userdata is set when initiating the client, here it is userdata=None
        :param mid: variable returned from the corresponding publish() call, to allow outgoing messages to be tracked
        :param properties: can be used in MQTTv5, but is optional
    """
    print("mid: " + str(mid))


# print which topic was subscribed to
def on_subscribe(client, userdata, mid, granted_qos, properties=None):
    """
        Prints a reassurance for successfully subscribing
        :param client: the client itself
        :param userdata: userdata is set when initiating the client, here it is userdata=None
        :param mid: variable returned from the corresponding publish() call, to allow outgoing messages to be tracked
        :param granted_qos: this is the qos that you declare when subscribing, use the same one for publishing
        :param properties: can be used in MQTTv5, but is optional
    """
    print("Subscribed: " + str(mid) + " " + str(granted_qos))


# print message, useful for checking if it was successful
def on_message(client, userdata, msg):
    """
        Prints a mqtt message to stdout ( used as callback for subscribe )
        :param client: the client itself
        :param userdata: userdata is set when initiating the client, here it is userdata=None
        :param msg: the message with topic and payload
    """

    print("message: " + msg.topic + " " + str(msg.qos) + " " + str(msg.payload))

# Dispatched function, adds player to a lobby & team
def add_player(client, topic_list, msg_payload):
    # Parse and Validate Input Data
    try:
        player = NewPlayer(**json.loads(msg_payload))
    except:
        print("ValidationError in create_game")
        return
    
    # If lobby doesn't exists...
    if player.lobby_name not in client.team_dict.keys():
        client.team_dict[player.lobby_name] = {}
        client.team_dict[player.lobby_name]['started'] = False

    if client.team_dict[player.lobby_name]['started']:
        publish_error_to_lobby(client, player.lobby_name, "Game has already started, please make a new lobby")

    add_team(client, player)

    print(f'Added Player: {player.player_name} to Team: {player.team_name}')


def add_team(client, player):
    # If team not in lobby, make new team and start a player list for the team
    if player.team_name not in client.team_dict[player.lobby_name].keys():
        client.team_dict[player.lobby_name][player.team_name] = [player.player_name,]    
    # If team already exists, add player to existing list
    else:
        client.team_dict[player.lobby_name][player.team_name].append(player.player_name)

move_to_Moveset = {
    'UP' : Moveset.UP,
    'DOWN' : Moveset.DOWN,
    'LEFT' : Moveset.LEFT,
    'RIGHT' : Moveset.RIGHT
}

# Dispatched Function: handles player movement commands
def player_move(client, topic_list, msg_payload):
    lobby_name = topic_list[1]
    player_name = topic_list[2]
    if lobby_name in client.team_dict.keys():
        try:
            new_move = msg_payload.decode()

            client.move_dict[lobby_name][player_name] = (player_name, move_to_Moveset[new_move])
            game: Game = client.game_dict[lobby_name]

            # If all players made a move, resolve movement
            if len(game.all_players) == len(client.move_dict[lobby_name]):
                for player, move in client.move_dict[lobby_name].values():
                    game.movePlayer(player, move)

                # Publish player states after all movement is resolved
                for player, _ in client.move_dict[lobby_name].values():
                    client.publish(f'games/{lobby_name}/{player}/game_state', json.dumps(game.getGameData(player)))

                # Clear move list
                client.move_dict[lobby_name].clear()
                print(game.map)
                client.publish(f'games/{lobby_name}/scores', json.dumps(game.getScores()))
                if game.gameOver():
                    # Publish game over, remove game
                    publish_to_lobby(client, lobby_name, "Game Over: All coins have been collected")
                    client.team_dict.pop(lobby_name)
                    client.move_dict.pop(lobby_name)
                    client.game_dict.pop(lobby_name)

        except Exception as e:
            raise e
            publish_error_to_lobby(client, lobby_name, e.__str__)
    else:
        publish_error_to_lobby(client, lobby_name, "Lobby name not found.")


# Dispatched function: Instantiates Game object
def start_game(client, topic_list, msg_payload):
    lobby_name = topic_list[1]
    if isinstance(msg_payload, bytes) and msg_payload.decode() == "START":

        if lobby_name in client.team_dict.keys():
                # create new game
                dict_copy = copy.deepcopy(client.team_dict[lobby_name])
                dict_copy.pop('started')

                game = Game(dict_copy)
                client.game_dict[lobby_name] = game
                client.move_dict[lobby_name] = OrderedDict()
                client.team_dict[lobby_name]["started"] = True

                for player in game.all_players.keys():
                    client.publish(f'games/{lobby_name}/{player}/game_state', json.dumps(game.getGameData(player)))


                print(game.map)
    elif isinstance(msg_payload, bytes) and msg_payload.decode() == "STOP":
        publish_to_lobby(client, lobby_name, "Game Over: Game has been stopped")
        client.team_dict.pop(lobby_name, None)
        client.move_dict.pop(lobby_name, None)
        client.game_dict.pop(lobby_name, None)


def publish_error_to_lobby(client, lobby_name, error):
    publish_to_lobby(client, lobby_name, f"Error: {error}")


def publish_to_lobby(client, lobby_name, msg):
    client.publish(f"games/{lobby_name}/lobby", msg)


def next_move(client, topic_list, msg_payload):
    lobby_name = topic_list[1]
    player_name = topic_list[2]
    if(player_name not in client.move_dict[lobby_name].keys()):
        values=json.loads(msg_payload)
        values={'obsticle':values['enemyPositions']+ values['walls'], 'coin':values['coin1']+values['coin2']+values['coin3']}
        #use values to make move
        client.publish(f'games/{lobby_name}/{player_name}/move', 'RIGHT')

dispatch = {
    'new_game' : add_player,
    'move' : player_move,
    'start' : start_game,
    'game_state' : next_move,
}

if __name__ == '__main__':
    load_dotenv(dotenv_path='./credentials.env')
    
    broker_address = os.environ.get('BROKER_ADDRESS')
    broker_port = int(os.environ.get('BROKER_PORT'))
    username = os.environ.get('USER_NAME')
    password = os.environ.get('PASSWORD')

    client = paho.Client(callback_api_version=paho.CallbackAPIVersion.VERSION1, client_id="Player1", userdata=None, protocol=paho.MQTTv5)
    
    # enable TLS for secure connection
    client.tls_set(tls_version=mqtt.client.ssl.PROTOCOL_TLS)
    # set username and password
    client.username_pw_set(username, password)
    # connect to HiveMQ Cloud on port 8883 (default for MQTT)
    client.connect(broker_address, broker_port)

    # setting callbacks, use separate functions like above for better visibility
    client.on_subscribe = on_subscribe # Can comment out to not print when subscribing to new topics
    client.on_message = on_message
    client.on_publish = on_publish # Can comment out to not print when publishing to topics

    client.loop_start()
    lobby_name = "Keen"
    team_name1="Red"
    team_name2="Blue"
    player_1 = "Leer"
    player_2 = "Lerry"

    client.subscribe(f"games/{lobby_name}/lobby")
    client.subscribe(f'games/{lobby_name}/+/game_state')
    client.subscribe(f'games/{lobby_name}/scores')
    client.publish("new_game", json.dumps({'lobby_name':lobby_name,
                                            'team_name':team_name1,
                                            'player_name' : player_1}))
    
    client.publish("new_game", json.dumps({'lobby_name':lobby_name,
                                            'team_name':team_name2,
                                            'player_name' : player_2}))

    time.sleep(1) # Wait a second to resolve game start
    client.publish(f"games/{lobby_name}/start", "START")
    while (True):
        time.sleep(2)
        #Takes in input from user
        player1Move = input(player_1 + ": ")
        #Uses the input to move
        client.publish(f"games/{lobby_name}/{player_1}/move", player1Move)
        time.sleep(2)
        #Takes in input from user
        player2Move = input(player_2 + ": ")
        #Uses the input to move
        client.publish(f"games/{lobby_name}/{player_2}/move", player2Move)

    
    client.loop_forever()
