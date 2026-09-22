<?php
/**
 * Plugin Name: Ready4site Digiseller Bridge
 * Description: Safe REST bridge for testing Digiseller API and syncing WooCommerce downloadable products with file delivery.
 * Version: 0.1.0
 * Author: Ready4site
 */
if (!defined('ABSPATH')) exit;

final class R4S_Digiseller_Bridge {
    const NS = 'r4s-digiseller-bridge/v1';
    const SETTINGS = 'r4s_digiseller_sync_settings';
    const META_ID = '_r4s_bridge_digiseller_id';
    const META_CONTENT_ID = '_r4s_bridge_digiseller_content_id';
    const META_LAST = '_r4s_bridge_digiseller_last_sync';

    public static function init() { add_action('rest_api_init', [__CLASS__, 'routes']); }
    public static function routes() {
        register_rest_route(self::NS, '/test', ['methods'=>'POST','callback'=>[__CLASS__,'test'],'permission_callback'=>function(){return current_user_can('manage_woocommerce');}]);
        register_rest_route(self::NS, '/sync/(?P<id>\\d+)', ['methods'=>'POST','callback'=>[__CLASS__,'sync'],'permission_callback'=>function(){return current_user_can('manage_woocommerce');}]);
        register_rest_route(self::NS, '/status/(?P<id>\\d+)', ['methods'=>'GET','callback'=>[__CLASS__,'status'],'permission_callback'=>function(){return current_user_can('manage_woocommerce');}]);
    }
    private static function settings(){ return (array)get_option(self::SETTINGS,[]); }
    private static function token(){
        $s=self::settings(); $seller=(int)($s['seller_id']??0); $key=trim((string)($s['api_key']??''));
        if(!$seller||!$key) return new WP_Error('missing_credentials','Digiseller credentials are missing.',['status'=>400]);
        $ts=time();
        $r=wp_remote_post('https://api.digiseller.com/api/apilogin',['timeout'=>30,'headers'=>['Accept'=>'application/json','Content-Type'=>'application/json'],'body'=>wp_json_encode(['seller_id'=>$seller,'timestamp'=>$ts,'sign'=>hash('sha256',$key.$ts)])]);
        if(is_wp_error($r)) return $r;
        $code=(int)wp_remote_retrieve_response_code($r); $j=json_decode(wp_remote_retrieve_body($r),true);
        if($code<200||$code>=300||!is_array($j)||(int)($j['retval']??-1)!==0||empty($j['token'])) return new WP_Error('login_failed','Digiseller login failed.',['status'=>502,'http'=>$code,'response'=>$j]);
        return (string)$j['token'];
    }
    public static function test(){
        $t=self::token(); if(is_wp_error($t)) return $t; $s=self::settings();
        return ['ok'=>true,'seller_id'=>(int)($s['seller_id']??0),'token_received'=>true];
    }
    public static function status($req){
        $id=(int)$req['id']; $p=wc_get_product($id);
        if(!$p) return new WP_Error('not_found','WooCommerce product not found.',['status'=>404]);
        $files=[]; foreach($p->get_downloads() as $d) $files[]=['id'=>$d->get_id(),'name'=>$d->get_name(),'file'=>$d->get_file()];
        return ['product_id'=>$id,'name'=>$p->get_name(),'downloadable'=>$p->is_downloadable(),'downloads'=>$files,'digiseller_id'=>(int)get_post_meta($id,self::META_ID,true),'content_id'=>(int)get_post_meta($id,self::META_CONTENT_ID,true),'last_sync'=>(string)get_post_meta($id,self::META_LAST,true)];
    }
    private static function plain($v){$v=strip_shortcodes((string)$v);$v=wp_strip_all_tags($v,true);return trim(html_entity_decode($v,ENT_QUOTES|ENT_HTML5,get_bloginfo('charset')?:'UTF-8'));}
    private static function json_request($method,$path,$payload,$token){
        $url='https://api.digiseller.com'.$path.(strpos($path,'?')===false?'?':'&').'token='.rawurlencode($token);
        $a=['method'=>$method,'timeout'=>45,'headers'=>['Accept'=>'application/json','Content-Type'=>'application/json']]; if($payload!==null)$a['body']=wp_json_encode($payload,JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES);
        $r=wp_remote_request($url,$a); if(is_wp_error($r)) return $r;
        $code=(int)wp_remote_retrieve_response_code($r);$raw=wp_remote_retrieve_body($r);$j=json_decode($raw,true);
        if($code<200||$code>=300||!is_array($j)) return new WP_Error('api_error','Digiseller API error.',['status'=>502,'http'=>$code,'body'=>$raw]);
        if(isset($j['retval'])&&(int)$j['retval']!==0) return new WP_Error('api_rejected','Digiseller rejected request.',['status'=>502,'response'=>$j]);
        return $j;
    }
    private static function fetch_download($url){
        require_once ABSPATH.'wp-admin/includes/file.php';
        if(preg_match('#^https?://#i',$url)){ $tmp=download_url($url,60); if(is_wp_error($tmp))return $tmp; return ['path'=>$tmp,'cleanup'=>true,'name'=>basename(parse_url($url,PHP_URL_PATH)?:'download.bin')];}
        $path=$url;if(strpos($url,ABSPATH)!==0&&file_exists(ABSPATH.ltrim($url,'/')))$path=ABSPATH.ltrim($url,'/');
        if(!is_readable($path))return new WP_Error('file_unreadable','WooCommerce download file is not readable.',['status'=>500,'file'=>$url]);
        return ['path'=>$path,'cleanup'=>false,'name'=>basename($path)];
    }
    private static function upload_file($product_id,$download_url,$token){
        $f=self::fetch_download($download_url);if(is_wp_error($f))return $f;$path=$f['path'];$filename=$f['name']?:basename($path);
        $contents=@file_get_contents($path);$mime=function_exists('mime_content_type')?@mime_content_type($path):'';if(!$mime)$mime='application/octet-stream';
        if($f['cleanup']&&file_exists($path))@unlink($path); if($contents===false)return new WP_Error('file_read','Cannot read WooCommerce download file.',['status'=>500]);
        $b='--------------------------'.wp_generate_password(24,false,false);
        $body='--'.$b."\r\n".'Content-Disposition: form-data; name="file"; filename="'.str_replace('"','',$filename).'"'."\r\n".'Content-Type: '.$mime."\r\n\r\n".$contents."\r\n--".$b."--\r\n";
        $url='https://api.digiseller.com/api/product/content/add/file/'.(int)$product_id.'?token='.rawurlencode($token);
        $r=wp_remote_post($url,['timeout'=>120,'headers'=>['Accept'=>'application/json','Content-Type'=>'multipart/form-data; boundary='.$b],'body'=>$body]);
        if(is_wp_error($r))return $r;$code=(int)wp_remote_retrieve_response_code($r);$raw=wp_remote_retrieve_body($r);$j=json_decode($raw,true);
        if($code<200||$code>=300||!is_array($j)||(isset($j['retval'])&&(int)$j['retval']!==0))return new WP_Error('upload_failed','Digiseller file upload failed.',['status'=>502,'http'=>$code,'response'=>$j,'body'=>$raw]);
        return $j;
    }
    public static function sync($req){
        $id=(int)$req['id'];$p=wc_get_product($id);if(!$p)return new WP_Error('not_found','WooCommerce product not found.',['status'=>404]);
        $downloads=$p->get_downloads();if(!$p->is_downloadable()||empty($downloads))return new WP_Error('no_file','Product has no WooCommerce download file.',['status'=>400]);
        $d=reset($downloads);$file=$d->get_file();if(!$file)return new WP_Error('no_file','Download URL is empty.',['status'=>400]);
        $token=self::token();if(is_wp_error($token))return $token;$s=self::settings();
        $name=self::plain($p->get_name());$desc=self::plain($p->get_description());if(!$desc)$desc=$name;$price=(float)$p->get_price();if($price<=0)return new WP_Error('bad_price','Product price must be positive.',['status'=>400]);
        $existing=(int)get_post_meta($id,self::META_ID,true);
        $payload=['content_type'=>'File','categories'=>[],'name'=>[['locale'=>'ru-RU','value'=>$name]],'description'=>[['locale'=>'ru-RU','value'=>$desc]],'add_info'=>[['locale'=>'ru-RU','value'=>'Страница товара: '.get_permalink($id)]],'price'=>['price'=>$price,'currency'=>(string)($s['currency']??'RUB')],'comission_partner'=>(int)($s['partner_commission']??0),'bonus'=>['enabled'=>false,'percent'=>0],'guarantee'=>['enabled'=>false,'value'=>0],'address_required'=>false,'enabled'=>true,'online_checkout_name'=>$name,'online_checkout_category'=>(string)($s['online_checkout_category']??'IntellectualPropertyGrant'),'online_checkout_tax'=>(string)($s['online_checkout_tax']??'no_vat')];
        if($existing){$c=self::json_request('POST','/api/product/edit/book/'.$existing,$payload,$token);if(is_wp_error($c))return $c;$dsid=$existing;$action='updated';}
        else{$c=self::json_request('POST','/api/product/create/book',$payload,$token);if(is_wp_error($c))return $c;$dsid=(int)($c['content']['product_id']??0);if(!$dsid)return new WP_Error('no_product_id','Digiseller returned no product_id.',['status'=>502,'response'=>$c]);update_post_meta($id,self::META_ID,$dsid);$action='created';}
        $u=self::upload_file($dsid,$file,$token);if(is_wp_error($u))return $u;$cid=(int)($u['content'][0]['content_id']??0);if($cid)update_post_meta($id,self::META_CONTENT_ID,$cid);update_post_meta($id,self::META_LAST,current_time('mysql'));
        return ['ok'=>true,'action'=>$action,'product_id'=>$id,'digiseller_id'=>$dsid,'content_id'=>$cid,'filename'=>$u['content'][0]['filename']??''];
    }
}
R4S_Digiseller_Bridge::init();
