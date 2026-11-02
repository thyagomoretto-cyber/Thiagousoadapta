param(
  [Parameter(Mandatory=$true)]
  [string]$Command
)

$MacHost = "100.125.190.61"
$MacUser = "thiagomoretto"

ssh "$MacUser@$MacHost" "~/.dodaios/bridge/ja-mac-exec.sh '$Command'"
