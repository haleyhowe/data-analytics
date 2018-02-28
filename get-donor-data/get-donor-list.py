#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
description: get the most recent donor list
version: 0.0.1
created: 2018-02-21
author: Ed Nykaza
dependencies:
    * requires that donors are accepted (currently a manual process)
    * requires a list of qa accounts on production to be ignored
    * requires environmental variables: import environmentalVariables.py
    * requires https://github.com/tidepool-org/command-line-data-tools
license: BSD-2-Clause
TODO:
* [] waiting for QA to cross reference donor accounts with testing accounts,
once they do, then the ignoreAccounts file needs to be updated
* [] once the process of accepting new donors is automated, the use of the
dateStamp will make more sense. As it is being used now, it is possible that
the dateStamp does NOT reflect all of the recent donors.
"""

# %% load in required libraries
import environmentalVariables
import pandas as pd
import datetime as dt
import numpy as np
import hashlib
import os
import sys
import subprocess as sub
import requests
import json


# %% user inputs (choices to be made to run code)
securePath = "/tidepoolSecure/data/"
ignoreAccountsPath = securePath + \
    "PHI-2018-02-28-prod-accounts-to-be-ignored.csv"

donorGroups = ["", "BT1", "carbdm", "CDN", "CWD", "DHF", "DIATRIBE",
               "diabetessisters", "DYF", "JDRF", "NSF", "T1DX"]


# %% define global variables
salt = os.environ["BIGDATA_SALT"]

dateStamp = dt.datetime.now().strftime("%Y") + "-" + \
    dt.datetime.now().strftime("%m") + "-" + \
    dt.datetime.now().strftime("%d")

phiDateStamp = "PHI-" + dateStamp

allDonorsList = pd.DataFrame(columns=["userID", "name", "donorGroup"])
donorBandDdayListColumns = ["userID", "bDay", "dDay", "hashID"]
allDonorBandDdayList = pd.DataFrame(columns=donorBandDdayListColumns)

# create output folders
donorFolder = securePath + phiDateStamp + "-donor-data/"
if not os.path.exists(donorFolder):
    os.makedirs(donorFolder)

donorListFolder = donorFolder + phiDateStamp + "-donorLists/"
if not os.path.exists(donorListFolder):
    os.makedirs(donorListFolder)

uniqueDonorPath = donorFolder + phiDateStamp + "-uniqueDonorList.csv"


# %% define functions
def get_donor_lists(email, password, outputDonorList):
    p = sub.Popen(["getusers", email,
                   "-p", password, "-o",
                   outputDonorList, "-v"], stdout=sub.PIPE, stderr=sub.PIPE)

    output, errors = p.communicate()
    output = output.decode("utf-8")
    errors = errors.decode("utf-8")

    if output.startswith("Successful login.\nSuccessful") is False:
        sys.exit("ERROR with" + email +
                 " ouput: " + output +
                 " errorMessage: " + errors)

    return


def load_donors(outputDonorList, donorGroup):
    donorList = []
    if os.stat(outputDonorList).st_size > 0:
        donorList = pd.read_csv(outputDonorList,
                                header=None,
                                usecols=[0, 1],
                                names=["userID", "name"],
                                low_memory=False)

        donorList["donorGroup"] = donorGroup

    return donorList


def get_bdays_and_ddays(email, password, donorBandDdayListColumns):

    tempBandDdayList = pd.DataFrame(columns=donorBandDdayListColumns)
    url1 = "https://api.tidepool.org/auth/login"
    myResponse = requests.post(url1, auth=(email, password))

    if(myResponse.ok):
        xtoken = myResponse.headers["x-tidepool-session-token"]
        userid = json.loads(myResponse.content.decode())["userid"]
        url2 = "https://api.tidepool.org/metadata/users/" + userid + "/users"
        headers = {
            "x-tidepool-session-token": xtoken,
            "Content-Type": "application/json"
        }

        myResponse2 = requests.get(url2, headers=headers)
        if(myResponse2.ok):

            usersData = json.loads(myResponse2.content.decode())

            for i in range(0, len(usersData)):
                try:
                    bDay = usersData[i]["profile"]["patient"]["birthday"]
                except Exception:
                    bDay = np.nan
                try:
                    dDay = usersData[i]["profile"]["patient"]["diagnosisDate"]
                except Exception:
                    dDay = np.nan
                userID = usersData[i]["userid"]
                usr_string = userID + salt
                hash_user = hashlib.sha256(usr_string.encode())
                hashID = hash_user.hexdigest()
                tempBandDdayList = tempBandDdayList.append(
                        pd.DataFrame([[userID,
                                       bDay,
                                       dDay,
                                       hashID]],
                                     columns=donorBandDdayListColumns),
                        ignore_index=True)
        else:
            print(donorGroup, "ERROR", myResponse2.status_code)
    else:
        print(donorGroup, "ERROR", myResponse.status_code)

    return tempBandDdayList


# %% loop through each donor group to get a list of donors, bdays, and ddays
for donorGroup in donorGroups:
    outputDonorList = donorListFolder + donorGroup + "-donors.csv"

    # get environmental variables
    email, password = \
        environmentalVariables.get_environmental_variables(donorGroup)

    # get the list of donors
    get_donor_lists(email, password, outputDonorList)

    # load in the donor list
    donorList = load_donors(outputDonorList, donorGroup)
    allDonorsList = allDonorsList.append(donorList, ignore_index=True)

    # load in bdays and ddays and append to all donor list
    donorBandDdayList = get_bdays_and_ddays(email,
                                            password,
                                            donorBandDdayListColumns)

    allDonorBandDdayList = allDonorBandDdayList.append(donorBandDdayList,
                                                       ignore_index=True)

    print("BIGDATA_" + donorGroup, "complete")

# %% save output

allDonorBandDdayList = pd.merge(allDonorBandDdayList,
                                allDonorsList,
                                how="left",
                                on="userID")

uniqueDonors = allDonorBandDdayList.loc[
        ~allDonorBandDdayList["userID"].duplicated()]

# cross reference the QA users here and DROP them
ignoreAccounts = pd.read_csv(ignoreAccountsPath, low_memory=False)
uniqueIgnoreAccounts = \
    ignoreAccounts[ignoreAccounts.Userid.notnull()].Userid.unique()

for ignoreAccount in uniqueIgnoreAccounts:
    uniqueDonors = uniqueDonors[uniqueDonors.userID != ignoreAccount]

uniqueDonors = uniqueDonors.reset_index(drop=True)
uniqueDonors.index.name = "dIndex"

print("There are",
      len(uniqueDonors),
      "unique donors, of the",
      len(allDonorsList),
      "records")
print("The total number of missing datapoints:",
      "\n",
      uniqueDonors.isnull().sum())

uniqueDonors.to_csv(uniqueDonorPath)
