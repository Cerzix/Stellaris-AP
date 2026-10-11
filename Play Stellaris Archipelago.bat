@echo off
rem Opens the client: connect to a multiworld there, then start Stellaris from it.
rem It stays open while you play and shows what happens. The same is written to client.log in this folder.
cd /d "%~dp0"
start "" pythonw -m stellaris_ap.app
