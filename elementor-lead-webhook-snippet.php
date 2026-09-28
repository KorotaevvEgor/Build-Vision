<?php
/**
 * =========================================================================
 * ЧТО НУЖНО ЗАМЕНИТЬ ПЕРЕД ИСПОЛЬЗОВАНИЕМ:
 *
 * 1) 'lead_form'   -> точное имя вашей формы (Elementor: настройки формы
 *                     -> Content -> Additional Options -> Form Name)
 *
 * 2) ID полей ниже (сейчас: name, email, phone, upload) -> замените на ID,
 *    которые видны в Elementor у каждого поля формы:
 *    откройте поле -> вкладка Advanced -> поле "ID"
 *
 * 3) $endpoint -> сейчас указан ваш тестовый webhook.site.
 *    Когда протестируете - замените на адрес вашей реальной апихи.
 * =========================================================================
 */

add_action( 'elementor_pro/forms/new_record', 'send_lead_to_my_api', 10, 2 );

function send_lead_to_my_api( $record, $ajax_handler ) {

    // 1) Имя формы ---------------------------------------------------------
    $form_name = $record->get_form_settings( 'form_name' );
    if ( 'lead_form' !== $form_name ) {
        return;
    }

    $raw_fields = $record->get( 'fields' );

    $data = [
        'name'    => '',
        'email'   => '',
        'phone'   => '',
        'message' => '',
    ];
    $file_path = '';
    $file_name = '';

    // 2) ID полей вашей формы ----------------------------------------------
    foreach ( $raw_fields as $id => $field ) {
        switch ( $id ) {
            case 'name':                 // Name
                $data['name'] = $field['value'];
                break;
            case 'email':                // Почта
                $data['email'] = $field['value'];
                break;
            case 'field_4df1657':        // Телефон
                $data['phone'] = $field['value'];
                break;
            case 'message':              // Сообщение
                $data['message'] = $field['value'];
                break;
            case 'field_15ef79c':        // Файл
                if ( ! empty( $field['value'] ) ) {
                    $upload_dir = wp_upload_dir();
                    // value - это URL файла, превращаем его в путь на диске
                    $file_url  = is_array( $field['value'] ) ? reset( $field['value'] ) : $field['value'];
                    $file_path = str_replace( $upload_dir['baseurl'], $upload_dir['basedir'], $file_url );
                    $file_name = basename( $file_path );
                }
                break;
        }
    }

    // 3) ЗАМЕНИТЕ адрес на боевую апиху, когда протестируете --------------
    $endpoint = 'https://webhook.site/8edffcb6-f6e0-4149-a387-3f52a293ccee'; // <-- СЮДА: URL вашей API

    $boundary = wp_generate_password( 24, false );
    $eol = "\r\n";
    $body = '';

    foreach ( $data as $key => $value ) {
        $body .= '--' . $boundary . $eol;
        $body .= 'Content-Disposition: form-data; name="' . $key . '"' . $eol . $eol;
        $body .= $value . $eol;
    }

    if ( $file_path && file_exists( $file_path ) ) {
        $body .= '--' . $boundary . $eol;
        $body .= 'Content-Disposition: form-data; name="file"; filename="' . $file_name . '"' . $eol;
        $body .= 'Content-Type: application/octet-stream' . $eol . $eol;
        $body .= file_get_contents( $file_path ) . $eol;
    }

    $body .= '--' . $boundary . '--' . $eol;

    $response = wp_remote_post( $endpoint, [
        'headers' => [ 'Content-Type' => 'multipart/form-data; boundary=' . $boundary ],
        // Если апихе нужна авторизация, раскомментируйте и впишите токен:
        // 'headers' => [
        //     'Content-Type'  => 'multipart/form-data; boundary=' . $boundary,
        //     'Authorization' => 'Bearer YOUR_TOKEN_HERE', // <-- СЮДА: токен
        // ],
        'body'    => $body,
        'timeout' => 30,
    ] );

    if ( is_wp_error( $response ) ) {
        error_log( 'Lead API webhook error: ' . $response->get_error_message() );
    }
}
