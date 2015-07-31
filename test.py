from azure import _validate_not_none,ETree
    
publish_settings_path = "C:\\Users\\v-zhongz\\Documents\\GitHub\\vminspector\\OSTC Shanghai Test-7-30-2015-credentials.publishsettings"

_validate_not_none('publish_settings_path', publish_settings_path)

# parse the publishsettings file and find the ManagementCertificate Entry
tree = ETree.parse(publish_settings_path)
subscriptions = tree.getroot().findall("./PublishProfile/Subscription")
subscription = subscriptions[0]
print subscription.get('Name')