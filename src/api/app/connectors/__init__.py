"""Cloud connectors.

Import submodules directly. Importing the registry from here cycles back
through the Azure connector while app.services.azure_resources is still loading.
"""
