import QtQuick 2.6
import QtQuick.Layouts 1.0
import QtQuick.Controls 2.14
import QtQuick.Controls.Material 2.0

import org.electrum_glc 1.0

import "controls"

ElDialog {
    id: dialog
    title: qsTr('Payment Request')

    property string key

    property string _bolt11
    property string _bip21uri
    property string _address

    property bool _render_qr: false // delay qr rendering until dialog is shown

    parent: Overlay.overlay
    modal: true
    standardButtons: Dialog.Close

    width: parent.width
    height: parent.height

    Overlay.modal: Rectangle {
        color: "#aa000000"
    }

    Flickable {
        anchors.fill: parent
        contentHeight: rootLayout.height
        clip:true
        interactive: height < contentHeight

        ColumnLayout {
            id: rootLayout
            width: parent.width
            spacing: constants.paddingMedium

            states: [
                State {
                    name: 'bolt11'
                    PropertyChanges { target: qrloader; sourceComponent: qri_bolt11 }
                    PropertyChanges { target: bolt11label; font.bold: true }
                },
                State {
                    name: 'bip21uri'
                    PropertyChanges { target: qrloader; sourceComponent: qri_bip21uri }
                    PropertyChanges { target: bip21label; font.bold: true }
                },
                State {
                    name: 'address'
                    PropertyChanges { target: qrloader; sourceComponent: qri_address }
                    PropertyChanges { target: addresslabel; font.bold: true }
                }
            ]

            Rectangle {
                height: 1
                Layout.fillWidth: true
                color: Material.accentColor
            }

            Item {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: constants.paddingSmall
                Layout.bottomMargin: constants.paddingSmall

                Layout.preferredWidth: qrloader.width
                Layout.preferredHeight: qrloader.height

                Loader {
                    id: qrloader
                    Component {
                        id: qri_bolt11
                        QRImage {
                            qrdata: _bolt11
                            render: _render_qr
                        }
                    }
                    Component {
                        id: qri_bip21uri
                        QRImage {
                            qrdata: _bip21uri
                            render: _render_qr
                        }
                    }
                    Component {
                        id: qri_address
                        QRImage {
                            qrdata: _address
                            render: _render_qr
                        }
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        if (rootLayout.state == 'bolt11') {
                            if (_bip21uri != '')
                                rootLayout.state = 'bip21uri'
                            else if (_address != '')
                                rootLayout.state = 'address'
                        } else if (rootLayout.state == 'bip21uri') {
                            if (_address != '')
                                rootLayout.state = 'address'
                            else if (_bolt11 != '')
                                rootLayout.state = 'bolt11'
                        } else if (rootLayout.state == 'address') {
                            if (_bolt11 != '')
                                rootLayout.state = 'bolt11'
                            else if (_bip21uri != '')
                                rootLayout.state = 'bip21uri'
                        }
                    }
                }
            }

            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: constants.paddingLarge
                Label {
                    id: bolt11label
                    text: qsTr('BOLT11')
                    color: _bolt11 ? Material.foreground : constants.mutedForeground
                }
                Rectangle {
                    Layout.preferredWidth: constants.paddingXXSmall
                    Layout.preferredHeight: constants.paddingXXSmall
                    radius: constants.paddingXXSmall / 2
                    color: Material.accentColor
                }
                Label {
                    id: bip21label
                    text: qsTr('BIP21')
                    color: _bip21uri ? Material.foreground : constants.mutedForeground
                }
                Rectangle {
                    Layout.preferredWidth: constants.paddingXXSmall
                    Layout.preferredHeight: constants.paddingXXSmall
                    radius: constants.paddingXXSmall / 2
                    color: Material.accentColor
                }
                Label {
                    id: addresslabel
                    text: qsTr('ADDRESS')
                    color: _address ? Material.foreground : constants.mutedForeground
                }
            }

            Rectangle {
                height: 1
                Layout.fillWidth: true
                color: Material.accentColor
            }

            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                Button {
                    icon.source: '../../icons/delete.png'
                    text: qsTr('Delete')
                    onClicked: {
                        Daemon.currentWallet.delete_request(request.key)
                        dialog.close()
                    }
                }
                Button {
                    icon.source: '../../icons/copy_bw.png'
                    icon.color: 'transparent'
                    text: 'Copy'
                    onClicked: {
                        if (request.isLightning && rootLayout.state == 'bolt11')
                            AppController.textToClipboard(_bolt11)
                        else if (rootLayout.state == 'bip21uri')
                            AppController.textToClipboard(_bip21uri)
                        else
                            AppController.textToClipboard(_address)
                    }
                }
                Button {
                    icon.source: '../../icons/share.png'
                    text: 'Share'
                    onClicked: {
                        enabled = false
                        if (request.isLightning && rootLayout.state == 'bolt11')
                            AppController.doShare(_bolt11, qsTr('Payment Request'))
                        else if (rootLayout.state == 'bip21uri')
                            AppController.doShare(_bip21uri, qsTr('Payment Request'))
                        else
                            AppController.doShare(_address, qsTr('Onchain address'))

                        enabled = true
                    }
                }
            }

            GridLayout {
                columns: 2

                Label {
                    visible: request.message != ''
                    text: qsTr('Description')
                }
                Label {
                    visible: request.message != ''
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: request.message
                    font.pixelSize: constants.fontSizeLarge
                }

                Label {
                    visible: request.amount.satsInt != 0
                    text: qsTr('Amount')
                }
                RowLayout {
                    visible: request.amount.satsInt != 0
                    Label {
                        text: Config.formatSats(request.amount)
                        font.family: FixedFont
                        font.pixelSize: constants.fontSizeLarge
                        font.bold: true
                    }
                    Label {
                        text: Config.baseUnit
                        color: Material.accentColor
                        font.pixelSize: constants.fontSizeLarge
                    }

                    Label {
                        id: fiatValue
                        Layout.fillWidth: true
                        text: Daemon.fx.enabled
                                ? '(' + Daemon.fx.fiatValue(request.amount, false) + ' ' + Daemon.fx.fiatCurrency + ')'
                                : ''
                        font.pixelSize: constants.fontSizeMedium
                        wrapMode: Text.Wrap
                    }
                }

                Label {
                    visible: request.address
                    text: qsTr('Address')
                }

                Label {
                    visible: request.address
                    Layout.fillWidth: true
                    font.family: FixedFont
                    font.pixelSize: constants.fontSizeLarge
                    wrapMode: Text.WrapAnywhere
                    text: request.address
                }

                Label {
                    text: qsTr('Status')
                }
                Label {
                    Layout.fillWidth: true
                    font.pixelSize: constants.fontSizeLarge
                    text: request.status_str
                }
            }
        }
    }

    Component.onCompleted: {
        if (!request.isLightning) {
            _bip21uri = request.bip21
            _address = request.address
            rootLayout.state = 'bip21uri'
        } else {
            _bolt11 = request.bolt11
            rootLayout.state = 'bolt11'
            if (request.address != '') {
                _bip21uri = request.bip21
                _address = request.address
            }
        }
    }

    RequestDetails {
        id: request
        wallet: Daemon.currentWallet
        key: dialog.key
    }

    // hack. delay qr rendering until dialog is shown
    Connections {
        target: dialog.enter
        function onRunningChanged() {
            if (!dialog.enter.running) {
                dialog._render_qr = true
            }
        }
    }
}
