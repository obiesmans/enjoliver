import os
import urllib2

from flask import Flask, request, json

app = application = Flask(__name__)

application.config["BOOTCFG_URI"] = os.getenv(
    "BOOTCFG_URI", "http://127.0.0.1:8080")

application.config["BOOTCFG_URLS"] = [
    "/",
    "/boot.ipxe",
    "/assets"
]


@application.route('/', methods=['GET'])
def root():
    """
    Map the API
    :return: available routes
    """
    links = [k.rule for k in app.url_map.iter_rules()
             if "/static/" != k.rule[:8]]

    return json.jsonify(links)


@application.route('/healthz', methods=['GET'])
def healthz():
    """
    Query all services and return the status
    :return: json
    """
    status = {
        "global": True,
        "flask": True,
        "bootcfg": {
            k: False for k in application.config["BOOTCFG_URLS"]}
    }
    for k in status["bootcfg"]:
        try:
            bootcfg_resp = urllib2.urlopen(
                "%s%s" % (app.config["BOOTCFG_URI"], k))
            assert bootcfg_resp.code == 200
            status["bootcfg"][k] = True
        except Exception as e:
            # app.log_exception(e.message)
            status["bootcfg"][k] = False
            status["global"] = False

    return json.jsonify(status)


@application.route('/discovery', methods=['POST'])
def discovery():
    request.form.to_dict()
    return "thank-you"


def insert_dhcp_retry(resp_list):
    """
    :param resp_list: the iPXE readlines response from bootcfg
    :return: the response with the dhcp retry
    """
    if len(resp_list) == 2 or len(resp_list) == 4:
        resp_list.insert(1, ":retry_dhcp\n")
        resp_list.insert(2, "dhcp || goto retry_dhcp\n")
    else:
        app.logger.warning("iPXE response is not coherent")
    return "".join(resp_list), 200


@application.route('/boot.ipxe', methods=['GET'])
def boot_ipxe():
    """
    Fetch the bootcfg/boot.ipxe and insert retry for dhcp
    :return: str
    """
    bootcfg_resp = urllib2.urlopen(
        "%s/boot.ipxe" % app.config["BOOTCFG_URI"])
    resp_list = bootcfg_resp.readlines()
    bootcfg_resp.close()
    return insert_dhcp_retry(resp_list)


@application.route('/ipxe', methods=['GET'])
def ipxe():
    """
    Fetch the bootcfg/ipxe?<key>=<value> and insert retry for dhcp
    :return: str
    """
    try:
        bootcfg_resp = urllib2.urlopen(
            "%s%s" % (
                app.config["BOOTCFG_URI"],
                request.full_path))
        resp_list = bootcfg_resp.readlines()
        bootcfg_resp.close()
        return insert_dhcp_retry(resp_list)

    except urllib2.URLError:
        return "404", 404


if __name__ == "__main__":
    application.run()
