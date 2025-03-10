import QtQuick 2.6
import QtQuick.Layouts 1.0
import QtQuick.Controls 2.3
import QtQuick.Controls.Material 2.0

import org.electrum_glc 1.0

import "controls"

Pane {
    id: rootItem
    objectName: 'WalletDetails'

    padding: 0

    function enableLightning() {
        var dialog = app.messageDialog.createObject(rootItem,
                {'text': qsTr('Enable Lightning for this wallet?'), 'yesno': true})
        dialog.yesClicked.connect(function() {
            Daemon.currentWallet.enableLightning()
        })
        dialog.open()
    }

    function deleteWallet() {
        var dialog = app.messageDialog.createObject(rootItem,
                {'text': qsTr('Really delete this wallet?'), 'yesno': true})
        dialog.yesClicked.connect(function() {
            Daemon.check_then_delete_wallet(Daemon.currentWallet)
        })
        dialog.open()
    }

    function changePassword() {
        // trigger dialog via wallet (auth then signal)
        Daemon.start_change_password()
    }

    function importAddressesKeys() {
        var dialog = importAddressesKeysDialog.createObject(rootItem)
        dialog.open()
    }

    ColumnLayout {
        id: rootLayout
        width: parent.width
        height: parent.height
        spacing: 0

        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: constants.paddingLarge

            contentHeight: flickableLayout.height
            clip:true
            interactive: height < contentHeight

            ColumnLayout {
                id: flickableLayout
                width: parent.width
                spacing: constants.paddingLarge

                RowLayout {
                    Label {
                        text: qsTr('Wallet:')
                        font.pixelSize: constants.fontSizeLarge
                        color: Material.accentColor
                    }

                    Label {
                        text: Daemon.currentWallet.name;
                        font.bold: true
                        font.pixelSize: constants.fontSizeLarge
                        Layout.fillWidth: true
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: Material.accentColor
                }

                GridLayout {
                    columns: 3
                    Layout.alignment: Qt.AlignHCenter

                    Tag {
                        Layout.alignment: Qt.AlignHCenter
                        text: Daemon.currentWallet.walletType
                        font.pixelSize: constants.fontSizeSmall
                        font.bold: true
                        iconSource: '../../../icons/wallet.png'
                    }
                    Tag {
                        Layout.alignment: Qt.AlignHCenter
                        text: Daemon.currentWallet.txinType
                        font.pixelSize: constants.fontSizeSmall
                        font.bold: true
                    }
                    Tag {
                        Layout.alignment: Qt.AlignHCenter
                        text: qsTr('HD')
                        visible: Daemon.currentWallet.isDeterministic
                        font.pixelSize: constants.fontSizeSmall
                        font.bold: true
                    }
                    Tag {
                        Layout.alignment: Qt.AlignHCenter
                        text: qsTr('Watch only')
                        visible: Daemon.currentWallet.isWatchOnly
                        font.pixelSize: constants.fontSizeSmall
                        font.bold: true
                        iconSource: '../../../icons/eye1.png'
                    }
                    Tag {
                        Layout.alignment: Qt.AlignHCenter
                        text: qsTr('Encrypted')
                        visible: Daemon.currentWallet.isEncrypted
                        font.pixelSize: constants.fontSizeSmall
                        font.bold: true
                        iconSource: '../../../icons/key.png'
                    }
                    Tag {
                        Layout.alignment: Qt.AlignHCenter
                        text: qsTr('HW')
                        visible: Daemon.currentWallet.isHardware
                        font.pixelSize: constants.fontSizeSmall
                        font.bold: true
                        iconSource: '../../../icons/seed.png'
                    }
                    Tag {
                        Layout.alignment: Qt.AlignHCenter
                        text: qsTr('Lightning')
                        visible: Daemon.currentWallet.isLightning
                        font.pixelSize: constants.fontSizeSmall
                        font.bold: true
                        iconSource: '../../../icons/lightning.png'
                    }
                    Tag {
                        Layout.alignment: Qt.AlignHCenter
                        text: qsTr('Seed')
                        visible: Daemon.currentWallet.hasSeed
                        font.pixelSize: constants.fontSizeSmall
                        font.bold: true
                        iconSource: '../../../icons/seed.png'
                    }
                }

                Piechart {
                    id: piechart
                    visible: Daemon.currentWallet.totalBalance.satsInt > 0
                    Layout.preferredWidth: parent.width
                    implicitHeight: 200 // TODO: sane value dependent on screen
                    innerOffset: 6
                    function updateSlices() {
                        var totalB = Daemon.currentWallet.totalBalance.satsInt
                        var onchainB = Daemon.currentWallet.confirmedBalance.satsInt
                        var frozenB = Daemon.currentWallet.frozenBalance.satsInt
                        var lnB = Daemon.currentWallet.lightningBalance.satsInt
                        piechart.slices = [
                            { v: (onchainB-frozenB)/totalB, color: constants.colorPiechartOnchain, text: 'On-chain' },
                            { v: frozenB/totalB, color: constants.colorPiechartFrozen, text: 'On-chain (frozen)' },
                            { v: lnB/totalB, color: constants.colorPiechartLightning, text: 'Lightning' }
                        ]
                    }
                }

                GridLayout {
                    visible: Daemon.currentWallet && Daemon.currentWallet.walletType == '2fa'
                    Layout.preferredWidth: parent.width

                    columns: 2

                    Label {
                        text: qsTr('2FA')
                        color: Material.accentColor
                    }

                    Label {
                        Layout.fillWidth: true
                        text: Daemon.currentWallet.canSignWithoutServer
                                ? qsTr('disabled (can sign without server')
                                : qsTr('enabled')
                    }

                    Label {
                        visible: !Daemon.currentWallet.canSignWithoutServer
                        text: qsTr('Remaining TX')
                        color: Material.accentColor
                    }

                    Label {
                        Layout.fillWidth: true
                        visible: !Daemon.currentWallet.canSignWithoutServer
                        text: 'tx_remaining' in Daemon.currentWallet.billingInfo
                                ? Daemon.currentWallet.billingInfo['tx_remaining']
                                : qsTr('unknown')
                    }

                    Label {
                        Layout.columnSpan: 2
                        visible: !Daemon.currentWallet.canSignWithoutServer
                        text: qsTr('Billing')
                        color: Material.accentColor
                    }

                    TextHighlightPane {
                        Layout.columnSpan: 2
                        Layout.fillWidth: true

                        ColumnLayout {
                            spacing: 0

                            ButtonGroup {
                                id: billinggroup
                                onCheckedButtonChanged: {
                                    Config.trustedcoinPrepay = checkedButton.value
                                }
                            }

                            Repeater {
                                model: AppController.plugin('trustedcoin').billingModel
                                delegate: RowLayout {
                                    RadioButton {
                                        ButtonGroup.group: billinggroup
                                        property string value: modelData.value
                                        text: modelData.text
                                        checked: modelData.value == Config.trustedcoinPrepay
                                    }
                                    Label {
                                        text: Config.formatSats(modelData.sats_per_tx)
                                        font.family: FixedFont
                                    }
                                    Label {
                                        text: Config.baseUnit + '/tx'
                                        color: Material.accentColor
                                    }
                                }
                            }
                        }
                    }

                }

                GridLayout {
                    id: detailsLayout
                    visible: Daemon.currentWallet
                    Layout.preferredWidth: parent.width

                    columns: 2
                    Label {
                        text: qsTr('Derivation prefix')
                        visible: Daemon.currentWallet.isDeterministic
                        color: Material.accentColor
                    }
                    Label {
                        text: Daemon.currentWallet.derivationPrefix
                        visible: Daemon.currentWallet.isDeterministic
                    }

                    Label {
                        visible: Daemon.currentWallet.masterPubkey
                        Layout.columnSpan:2; text: qsTr('Master Public Key'); color: Material.accentColor
                    }

                    TextHighlightPane {
                        visible: Daemon.currentWallet.masterPubkey

                        Layout.columnSpan: 2
                        Layout.fillWidth: true
                        padding: 0
                        leftPadding: constants.paddingSmall

                        RowLayout {
                            width: parent.width
                            Label {
                                text: Daemon.currentWallet.masterPubkey
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                                font.family: FixedFont
                                font.pixelSize: constants.fontSizeMedium
                            }
                            ToolButton {
                                icon.source: '../../icons/share.png'
                                icon.color: 'transparent'
                                onClicked: {
                                    var dialog = app.genericShareDialog.createObject(rootItem, {
                                        title: qsTr('Master Public Key'),
                                        text: Daemon.currentWallet.masterPubkey
                                    })
                                    dialog.open()
                                }
                            }
                        }
                    }
                }
            }
        }

        FlatButton {
            Layout.fillWidth: true
            visible: Daemon.currentWallet.walletType == 'imported'
            text: Daemon.currentWallet.isWatchOnly
                    ? qsTr('Import additional addresses')
                    : qsTr('Import additional keys')
            onClicked: rootItem.importAddressesKeys()
        }
        FlatButton {
            Layout.fillWidth: true
            text: qsTr('Change Password')
            onClicked: rootItem.changePassword()
            icon.source: '../../icons/lock.png'
        }
        FlatButton {
            Layout.fillWidth: true
            text: qsTr('Delete Wallet')
            onClicked: rootItem.deleteWallet()
            icon.source: '../../icons/delete.png'
        }
        FlatButton {
            Layout.fillWidth: true
            text: qsTr('Enable Lightning')
            onClicked: rootItem.enableLightning()
            visible: Daemon.currentWallet && Daemon.currentWallet.canHaveLightning && !Daemon.currentWallet.isLightning
            icon.source: '../../icons/lightning.png'
        }
    }

    Connections {
        target: Daemon
        function onWalletLoaded() {
            Daemon.availableWallets.reload()
            app.stack.pop()
        }
        function onRequestNewPassword() { // new unified password (all wallets)
            var dialog = app.passwordDialog.createObject(app,
                    {
                        'confirmPassword': true,
                        'title': qsTr('Enter new password'),
                        'infotext': qsTr('If you forget your password, you\'ll need to\
                        restore from seed. Please make sure you have your seed stored safely')
                    } )
            dialog.accepted.connect(function() {
                Daemon.set_password(dialog.password)
            })
            dialog.open()
        }
        function onWalletDeleteError(code, message) {
            if (code == 'unpaid_requests') {
                var dialog = app.messageDialog.createObject(app, {text: message, yesno: true })
                dialog.yesClicked.connect(function() {
                    Daemon.check_then_delete_wallet(Daemon.currentWallet, true)
                })
                dialog.open()
            } else if (code == 'balance') {
                var dialog = app.messageDialog.createObject(app, {text: message, yesno: true })
                dialog.yesClicked.connect(function() {
                    Daemon.check_then_delete_wallet(Daemon.currentWallet, true, true)
                })
                dialog.open()
            } else {
                var dialog = app.messageDialog.createObject(app, {text: message })
                dialog.open()
            }
        }
    }

    Connections {
        target: Daemon.currentWallet
        function onRequestNewPassword() { // new wallet password
            var dialog = app.passwordDialog.createObject(app,
                    {
                        'confirmPassword': true,
                        'title': qsTr('Enter new password'),
                        'infotext': qsTr('If you forget your password, you\'ll need to\
                        restore from seed. Please make sure you have your seed stored safely')
                    } )
            dialog.accepted.connect(function() {
                Daemon.currentWallet.set_password(dialog.password)
            })
            dialog.open()
        }
        function onBalanceChanged() {
            piechart.updateSlices()
        }
    }

    Component {
        id: importAddressesKeysDialog
        ImportAddressesKeysDialog {
            width: parent.width
            height: parent.height
            onClosed: destroy()
        }
    }

    Component.onCompleted: {
        piechart.updateSlices()
    }

}
