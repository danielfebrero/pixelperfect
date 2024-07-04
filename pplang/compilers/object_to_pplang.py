import logging
import json
import re
import time

# Configure logging
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')

# Use a dictionary to store pointers
pointers_names = {}
unicode_map = []
reserved_chars = set()
unicode_to_index = {}

def load_reserved_chars(filename):
    with open(filename, 'r') as file:
        for line in file:
            reserved_chars.update(line.strip())

def load_unicode_map(filename):
    with open(filename, 'r') as file:
        unicode_map.extend(file.read().strip())
        for idx, char in enumerate(unicode_map):
            unicode_to_index[char] = idx

load_reserved_chars("pplang/hard/reserved")
load_unicode_map("pplang/hard/unicodes")

def ensure_size(lst, index):
    if len(lst) <= index:
        lst.extend([None] * (index + 1 - len(lst)))

def get_dictionary(pointer):
    dictionary = {}
    dictionary_pixels = []
    try:
        with open(f"pplang/pointers/{pointer}", 'r') as file:
            for line in file:
                if line:
                    pixel = line[0]
                    human = line.strip()[1:]
                    dictionary[human] = pixel
                    dictionary_pixels.append(pixel)
        return [dictionary, dictionary_pixels]
    except FileNotFoundError:
        logging.error(f"Pointer file not found: {pointer}")

def get_pointer_names(pointer):
    if pointer in pointers_names:
        return pointers_names[pointer]

    self_pointers_names = []
    try:
        with open(f"pplang/pointers/{pointer}", 'r') as file:
            for line in file:
                line = line.strip()
                if line:
                    match = re.match(r"(\d+)(.+)", line)
                    if match:
                        index = int(match.group(1))
                        value = match.group(2).strip()
                        ensure_size(self_pointers_names, index)
                        self_pointers_names[index] = value
    except FileNotFoundError:
        logging.error(f"Pointer file not found: {pointer}")

    pointers_names[pointer] = self_pointers_names
    return self_pointers_names

def parse_schema(schema):
    formatted_string = schema.replace("{", '{"').replace("}", '"}').replace(":", '": "').replace(",", '", "')
    if formatted_string[0] == "[" or formatted_string == "{":
        try:
            return json.loads(formatted_string)
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse schema: {e}")
            return {}
    else:
        return formatted_string

def get_pointer_pos(pointers_pos, pointer, name):
    if pointer not in pointers_pos:
        pointers_pos[pointer] = {}

    if name in pointers_pos[pointer]:
        return pointers_pos[pointer][name]

    try:
        with open(f"pplang/pointers/{pointer}", 'r') as file:
            for line in file:
                line = line.strip()
                if line:
                    match = re.match(r"(\d+)(.+)", line)
                    if match:
                        index = int(match.group(1))
                        value = match.group(2).strip()
                        if value == name:
                            pointers_pos[pointer][name] = index
                            return index
    except FileNotFoundError:
        logging.error(f"Pointer file not found: {pointer}")

    return None

def translate_with_priority(big_string, translations):
    # Sort dictionary keys by length in descending order
    sorted_keys = sorted(translations.keys(), key=len, reverse=True)

    i = 0
    max_key_length = len(sorted_keys[0]) if sorted_keys else 0
    while i < len(big_string):
        matched = False
        # Start with the maximum length of the keys and decrease to 2
        for length in range(max_key_length, 1, -1):
            if i + length > len(big_string):
                continue
            for key in sorted_keys:
                if len(key) == length and big_string[i:i+len(key)] == key:
                    yield translations[key]
                    i += len(key)
                    matched = True
                    break
            if matched:
                break
        if not matched:
            # If no match, yield the current character and move to the next
            yield big_string[i]
            i += 1

def process_object(schema, obj):
    self_pointers_pos = {}

    if isinstance(schema, list):
        compiled_result = []
        for item in obj:
            compiled_item = [None] * len(schema[0])
            idx = 0
            for key, value in schema[0].items():
                if value in item:
                    if idx == 0:
                        self_pointers_pos[key] = {}
                    item_value = item[value]
                    key_pointer_index = get_pointer_pos(self_pointers_pos, key, item_value)
                    compiled_item[idx] = key_pointer_index
                    idx += 1
            compiled_result.append(compiled_item)

        return compiled_result
    elif isinstance(schema, dict):
        compiled_item = [None] * len(schema)
        idx = 0
        for key, value in schema.items():
            if value in obj or value[0] == "+":
                if idx == 0:
                    self_pointers_pos[key] = {}
                if value[0] == "+":
                    const_names = get_pointer_names("+")
                    item_key = const_names[int(value[1:])]
                    item_value = obj[item_key]
                else:
                    item_value = obj[value]
                if key == "*":
                    compiled_item[idx] = f"*({item_value})"
                elif key[0] == "+":
                    compiled_item[idx] = f"({item_value})"
                else:
                    key_pointer_index = get_pointer_pos(self_pointers_pos, key, item_value)
                    compiled_item[idx] = key_pointer_index
                idx += 1

        return compiled_item
    else:
        compiled_item = ""
        char_gen = next_char(obj)
        [dictionary, dictionary_pixels] = get_dictionary(schema)
        for char in char_gen:
            if char in dictionary or (char == " " and "" in dictionary):
                compiled_item = compiled_item + dictionary[char.strip()]
            elif char in dictionary_pixels:
                compiled_item = compiled_item + "\\" + char
            else:
                compiled_item = compiled_item + char
        translated = ''.join(translate_with_priority(compiled_item, dictionary))  # Ensure generator is fully consumed
        return translated

# Convert numbers to corresponding Unicode characters and escape reserved characters, excluding floating point numbers
def convert_num(num):
    if num.isdigit():
        index = int(num)
        if 0 <= index < len(unicode_map):
            unicode_char = unicode_map[index]
            if unicode_char in reserved_chars:
                return f"\\{unicode_char}"
            return unicode_char
    return num

def replace_at_index(s, index, replacement):
    # Check if the index is within the valid range
    if index < 0 or index >= len(s):
        raise IndexError("Index out of range")
    # Create a new string with the replacement
    return s[:index] + replacement + s[index+1:]

def compile(pointer, obj):
    start_time = time.time()

    schema_pointers_names = get_pointer_names(pointer)
    schema_pointer_pos = get_pointer_pos({}, "=", pointer)

    raw_schema = schema_pointers_names[0] if schema_pointers_names else ""
    schema = parse_schema(raw_schema)

    processed_obj = process_object(schema, obj)
    stringified_obj = f"{processed_obj}"
    stringified_obj = stringified_obj.replace("\\'", "'")

    if stringified_obj[0] == "[" and stringified_obj[1] != "[":
        stringified_obj = replace_at_index(stringified_obj, 0, "{")
        stringified_obj = replace_at_index(stringified_obj, len(stringified_obj) - 1, "}")

    compiled_result = f"${schema_pointer_pos}{stringified_obj}".replace('\\\\', '\\').replace("'*", "*").replace("'`", "`").replace("`'", "`").replace(" ", "").replace("None", "-").replace("],[", '|').replace("[[", "[").replace("]]", "]").replace(")'", ")").replace("'(", "(")
    print(f"before unicode:: {compiled_result}")

    # Regex to match digits that are not part of floating point numbers
    parts = re.split(r'(?<!\\)(\d+\.\d+|\d+|.)', compiled_result)
    unicode_result = ''.join(convert_num(part) if part.isdigit() else part for part in parts if part)

    end_time = time.time()
    logging.warning(f"Compilation time: {end_time - start_time:.6f} seconds")

    return unicode_result

def next_char(compiled_str):
    for char in compiled_str:
        yield char

def uncompile(compiled_str):
    start_time = time.time()

    char_gen = next_char(compiled_str)
    decoded_data = ""
    is_escaped = False
    schema = []
    parent_schema = []
    current_operation = ""
    x_schema = 0
    x_object = 0
    decodeding_up_to = ""
    in_nested_build = False

    for char in char_gen:
        decodeding_up_to = decodeding_up_to + char
        if char == '\\' and not is_escaped:
            is_escaped = True
        elif char == "{" and not is_escaped:
            x_object = 0
            decoded_data = f"{decoded_data}{char}"
            current_operation = "{"
        elif char == "}" and not is_escaped:
            decoded_data = f"{decoded_data}{char}"
        elif char == "(" and not is_escaped:
            if not in_nested_build:
                key = list(schema[0].keys())[x_object]
                if schema[0][key][0] == "+":
                    pointer_name = get_pointer_names("+")[int(schema[0][key][1:])]
                    decoded_data = f"{decoded_data}\"{pointer_name}\":\""
                else:
                    decoded_data = f"{decoded_data}\"{schema[0][key]}\":\""
            current_operation = "("
        elif char == ")" and not is_escaped:
            if in_nested_build:
                schema = parent_schema
                in_nested_build = False
            else:
                decoded_data = f"{decoded_data}\""
        elif char == '$' and not is_escaped:
            x_object = 0
            current_operation = "$"
        elif char == "[" and not is_escaped:
            x_object = 0
            decoded_data = f"{decoded_data}{char}"
            current_operation = "[{"
        elif char == ',' and not is_escaped:
            decoded_data = f"{decoded_data}{char}"
            x_object += 1
        elif char == ']' and not is_escaped:
            if current_operation == "{":
                decoded_data = f"{decoded_data}{'}'}{char}"
            else:
                decoded_data = f"{decoded_data}{char}"
            current_operation = "{"
            x_object = 0
        elif char == '|' and not is_escaped:
            if current_operation == "{":
                decoded_data = f"{decoded_data}{'}'},{'{'}"
            else:
                decoded_data = f"{decoded_data}],["
            x_object = 0
            current_operation = "{"
        else:
            is_escaped = False
            pos = int(unicode_to_index.get(char, -1))

            if current_operation == "$":
                schema_list_pointers_names = get_pointer_names("=")
                schema_name = schema_list_pointers_names[pos]
                raw_schema = get_pointer_names(schema_name)[0]
                unkown_schema = parse_schema(raw_schema)
                parent_schema = schema
                if isinstance(unkown_schema, dict):
                    schema = [unkown_schema]
                else:
                    schema = unkown_schema
                current_operation = ""
            elif current_operation == "(":
                decoded_data = f"{decoded_data}{char}"
            elif current_operation == "[{":
                key = list(schema[0].keys())[x_object]
                if char == "-":
                    decoded_data = f"{decoded_data}{'{'}\"{schema[0][key]}\":null"
                else:
                    pointer_names = get_pointer_names(key)
                    pointer_name = pointer_names[pos] if len(pointer_names) > pos else "null"
                    decoded_data = f"{decoded_data}{'{'}\"{schema[0][key]}\":\"{pointer_name}\""
                current_operation = "{"
            elif current_operation == "{":
                key = list(schema[0].keys())[x_object]
                if char == "-":
                    decoded_data = f"{decoded_data}\"{schema[0][key]}\":null"
                elif char == "*":
                    in_nested_build = True
                    decoded_data = f"{decoded_data}\"{schema[0][key]}\":"
                else:
                    pointer_names = get_pointer_names(key)
                    pointer_name = pointer_names[pos] if len(pointer_names) > pos else "null"
                    decoded_data = f"{decoded_data}\"{schema[0][key]}\":\"{pointer_name}\""

    decoded_data = ''.join(decoded_data)

    try:
        compiled_list = json.loads(decoded_data)
    except json.JSONDecodeError as e:
        logging.error(f"Failed to parse decoded data: {e}")
        return None

    end_time = time.time()
    logging.warning(f"Uncompilation time: {end_time - start_time:.6f} seconds")

    return compiled_list

# Example usage
pointer = 'ui_color_palette_schema'
data = [
    {"color": "Beige", "type": "Secondary color", "score": 0.9999566078186035},
    {"color": "Cyan", "type": "Notification highlight color", "score": 0.9999328851699829},
    {"color": "Pink", "type": "Accent color", "score": 0.9999185800552368},
    {"color": "AliceBlue", "type": "Text color", "score": 0.999894380569458},
    {"color": "WhiteSmoke", "type": "Border color", "score": 0.9998866319656372},
    {"color": "Purple", "type": "Highlight color", "score": 0.9998842477798462},
    {"color": "Azure", "type": "Main color", "score": 0.9998782873153687},
    {"color": "AntiqueWhite", "type": "Alert color", "score": 0.9998581409454346},
    {"color": "DarkGray", "type": "Subtle background color", "score": 0.9996941089630127}
]

data_color_palet_response = {
    "color_palet": """$\$[¾,"|ʹ,&|ャ,%|-,#|-,\(|両,\$|~,!|-,\)|-,']""",
    "inference_time": 2.1053810119628906,
}

data_string = "hello, what's up today? anything wou would like to discuss?"

# compiled_data = compile(pointer, data)
# print("Compiled Data:")
# print(compiled_data)

# uncompiled_data = uncompile(compiled_data)
# print("Uncompiled Data:")
# print(uncompiled_data)

# corrupted_data = uncompile(f"{compiled_data[:5]}l{compiled_data[5:]}")
# print("Corrupted Data:")
# print(corrupted_data)

# compiled_colorpaletresponse_data = compile("ui_color_palette_response", data_color_palet_response)
# print("Compiled ColorPaletResonse Data:")
# print(compiled_colorpaletresponse_data)

# uncompiled_colorpaletresponse_data = uncompile(compiled_colorpaletresponse_data)
# print("Uncompiled ColorPaletResonse Data:")
# print(uncompiled_colorpaletresponse_data)

compiled_string = compile("string", data_string)
print("Compiled compiled_string Data:")
print(compiled_string)
