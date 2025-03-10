import QtQuick 2.6
import QtQuick.Layouts 1.0
import QtQuick.Controls 2.14
import QtQuick.Controls.Material 2.0

import org.electrum_glc 1.0

import "controls"

ElDialog {
    id: dialog

    title: qsTr('LNURL Payment request')
    iconSource: '../../../icons/link.png'

    property InvoiceParser invoiceParser

    standardButtons: Dialog.Cancel

    modal: true
    parent: Overlay.overlay
    Overlay.modal: Rectangle {
        color: "#aa000000"
    }

    GridLayout {
        columns: 2

        width: parent.width

        Label {
            text: qsTr('Provider')
            color: Material.accentColor
        }
        Label {
            text: invoiceParser.lnurlData['domain']
        }
        Label {
            text: qsTr('Description')
            color: Material.accentColor
        }
        Label {
            text: invoiceParser.lnurlData['metadata_plaintext']
            Layout.fillWidth: true
            wrapMode: Text.Wrap
        }
        Label {
            text: invoiceParser.lnurlData['min_sendable_sat'] == invoiceParser.lnurlData['max_sendable_sat']
                    ? qsTr('Amount')
                    : qsTr('Amount range')
            color: Material.accentColor
        }
        Label {
            text: invoiceParser.lnurlData['min_sendable_sat'] == invoiceParser.lnurlData['max_sendable_sat']
                    ? invoiceParser.lnurlData['min_sendable_sat'] == 0
                        ? qsTr('Unspecified')
                        : invoiceParser.lnurlData['min_sendable_sat']
                    : invoiceParser.lnurlData['min_sendable_sat'] + ' < amount < ' + invoiceParser.lnurlData['max_sendable_sat']
        }

        TextArea {
            id: comment
            visible: invoiceParser.lnurlData['comment_allowed'] > 0
            Layout.columnSpan: 2
            Layout.preferredWidth: parent.width
            Layout.minimumHeight: 80
            wrapMode: TextEdit.Wrap
            placeholderText: qsTr('Enter an (optional) message for the receiver')
        }

        Button {
            Layout.columnSpan: 2
            Layout.alignment: Qt.AlignHCenter
            text: qsTr('Proceed')
            onClicked: {
                invoiceParser.lnurlGetInvoice(invoiceParser.lnurlData['min_sendable_sat'], comment.text)
                dialog.close()
            }
        }
    }
}
