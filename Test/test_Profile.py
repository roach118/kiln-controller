from lib.oven import Profile
import os
import json

def get_profile(file = "test-fast.json"):
    profile_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Test', file))
    print(profile_path)
    with open(profile_path) as infile:
        profile_json = json.dumps(json.load(infile))
    profile = Profile(profile_json)

    return profile


def test_get_target_temperature():
    profile = get_profile()

    temperature = profile.get_target_temperature(3000)
    assert int(temperature) == 93

    temperature = profile.get_target_temperature(6004)
    assert round(temperature, 2) == 427.22


def test_find_time_from_temperature():
    profile = get_profile()

    time = profile.find_next_time_from_temperature(260.0)
    assert time == 4800

    time = profile.find_next_time_from_temperature(1095.56)
    assert time == 10857.6

    time = profile.find_next_time_from_temperature(1037.78)
    assert time == 10400.0



def test_find_time_odd_profile():
    profile = get_profile("test-cases.json")

    time = profile.find_next_time_from_temperature(260.0)
    assert time == 4200

    time = profile.find_next_time_from_temperature(1106.11)
    assert time == 16676.0


def test_find_x_given_y_on_line_from_two_points():
    profile = get_profile()

    y = 260.0
    p1 = [3600, 93.33]
    p2 = [10800, 1093.33]
    time = profile.find_x_given_y_on_line_from_two_points(y, p1, p2)

    assert time == 4800

    y = 260.0
    p1 = [3600, 93.33]
    p2 = [10800, 93.33]
    time = profile.find_x_given_y_on_line_from_two_points(y, p1, p2)

    assert time == 0

    y = 260.0
    p1 = [3600, 315.56]
    p2 = [10800, 315.56]
    time = profile.find_x_given_y_on_line_from_two_points(y, p1, p2)

    assert time == 0

    y = 260.0
    p1 = [3600, 260.0]
    p2 = [10800, 260.0]
    time = profile.find_x_given_y_on_line_from_two_points(y, p1, p2)

    assert time == 0
