import json
from config import CONFIG


class Profile:
    def __init__(self, json_data):
        obj = json.loads(json_data)
        self.name = obj["name"]
        self.data = sorted(obj["data"])
        self._validate_profile()

    def _validate_profile(self):
        min_temp = CONFIG.run.profile_min_temp_c
        max_temp = CONFIG.run.profile_max_temp_c
        if not self.data:
            raise ValueError("profile has no points")
        for idx, point in enumerate(self.data):
            if len(point) < 2:
                raise ValueError(f"profile point {idx} missing temperature")
            temp = point[1]
            if temp < min_temp:
                raise ValueError(
                    f"profile point {idx} temperature {temp} below minimum {min_temp}"
                )
            if temp > max_temp:
                raise ValueError(
                    f"profile point {idx} temperature {temp} above maximum {max_temp}"
                )

    def get_duration(self):
        return max([t for (t, x) in self.data])

    #  x = (y-y1)(x2-x1)/(y2-y1) + x1
    @staticmethod
    def find_x_given_y_on_line_from_two_points(y, point1, point2):
        if point1[0] > point2[0]:
            return 0  # time2 before time1 makes no sense in kiln segment
        if point1[1] >= point2[1]:
            return 0  # Zero will crash. Negative temperature slope, don't seek time.
        x = (y - point1[1]) * (point2[0] - point1[0]) / (point2[1] - point1[1]) + point1[0]
        return x

    def find_next_time_from_temperature(self, temperature):
        # The seek function will not do anything if this returns zero.
        time = 0
        for index, point2 in enumerate(self.data):
            if point2[1] >= temperature:
                if index > 0:  # Zero here would be before the first segment
                    if self.data[index - 1][1] <= temperature:  # We have an intersection
                        time = self.find_x_given_y_on_line_from_two_points(
                            temperature, self.data[index - 1], point2
                        )
                        if time == 0:
                            if self.data[index - 1][1] == point2[1]:
                                time = self.data[index - 1][0]
                                break

        return time

    def get_surrounding_points(self, time):
        if time > self.get_duration():
            return (None, None)

        prev_point = None
        next_point = None

        for i in range(len(self.data)):
            if time < self.data[i][0]:
                prev_point = self.data[i - 1]
                next_point = self.data[i]
                break

        return (prev_point, next_point)

    def get_target_temperature(self, time):
        if time > self.get_duration():
            return 0

        (prev_point, next_point) = self.get_surrounding_points(time)

        incl = float(next_point[1] - prev_point[1]) / float(next_point[0] - prev_point[0])
        temp = prev_point[1] + (time - prev_point[0]) * incl
        return temp

