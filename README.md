# vminspector
Retrieve EXT2/3/4 files from vhd which is stored in Azure Storage.

Functionality
==========
You can use vminspector to retrieve your file from Azure Storage need not to turn on you Virtual Machine.    

You should prepare your **azure publish settings** and set it in **config.py** to access your vhd file.

Installation
============
Download the repo using git

	git clone https://github.com/v-zhongz/vminspector

Dependencies
============

Python module: Construct==2.5.2, azure, requests.    

    (sudo) pip install Construct==2.5.2 azure requests

Usage
=====
After installation of the tool and dependencies, you can run the script by following command:

    python inspector.py <url of the vhd>

After the following displaying, the current directory is root directory now:

	/ $ 
	
Command
=====
To change current directory, use:

	cd <absolute path or relative path>
	
To download a file, use:

	download <absolute path or relative path>
	
To List files in current directory, use:

	ls

To end the python script, use:

	quit
	
Issue
=====
- For the time being, this tool can only be used to retrieve file remotely, but can not be used to revise the vhd file. However, revisability is a more practical functionality we want, and it's on the schedule.
- It would take approximately 15s to retrieve a single file.